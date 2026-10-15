#!/usr/bin/env python3
"""Backtest a v4.17/v4.18 factor composite from the real forward ledger.

The v4.18 scorer only changed trade weights relative to v4.17; factor formulas,
caps and registry inputs are identical.  Therefore selecting MeanRev/Flow from
v4.17 and Breakout/Fundamental/Growth from v4.18 does not create different
factor values.  The testable choice is the composite weighting.

This script intentionally:
  * uses the daily-last snapshot for each symbol/date;
  * joins the exact forward outcome by pred_id;
  * evaluates daily cross-sectional Spearman IC;
  * compares top-quintile returns on the same observations;
  * reports the full window and the latest 30% of dates separately.

It does not alter production scoring or write to Supabase.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent
PRED_GLOB = str(ROOT / "output/history/v2f_predictions_v4/*.jsonl")
OUT_GLOB = str(ROOT / "output/history/v2f_outcomes_v4/*.jsonl")
VERSIONS = {"v4.17", "v4.18"}
FACTORS = ("mean_reversion", "breakout", "flow", "fundamental", "growth")
HORIZONS = (3, 5, 10)

WEIGHT_SETS = {
    "v4.17": {
        "mean_reversion": 0.2700,
        "breakout": 0.1307,
        "flow": 0.2724,
        "fundamental": 0.2179,
        "growth": 0.1090,
    },
    "v4.18": {
        "mean_reversion": 0.5000,
        "breakout": 0.0500,
        "flow": 0.1500,
        "fundamental": 0.2000,
        "growth": 0.1000,
    },
    "hybrid_equal": {factor: 0.20 for factor in FACTORS},
    "hybrid_no_mr": {
        "mean_reversion": 0.00,
        "breakout": 0.25,
        "flow": 0.25,
        "fundamental": 0.25,
        "growth": 0.25,
    },
}


@dataclass(frozen=True)
class Observation:
    date: str
    symbol: str
    source_version: str
    factors: dict[str, float]
    gates: dict[str, float]
    returns: dict[int, float]
    actual_score: float


def _load_jsonl(pattern: str) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if row.get("scoring_version") in VERSIONS:
                    rows.append(row)
    return rows


def _number(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _snapshot_key(row: dict) -> tuple[str, str, str, int]:
    return (
        str(row.get("signal_date") or ""),
        str(row.get("snap_time") or ""),
        str(row.get("pred_id") or ""),
        1 if row.get("scoring_version") == "v4.18" else 0,
    )


def build_observations() -> list[Observation]:
    predictions = _load_jsonl(PRED_GLOB)
    outcomes = _load_jsonl(OUT_GLOB)
    outcome_by_id = {row.get("pred_id"): row for row in outcomes if row.get("pred_id")}

    # One observation per symbol/date across both sequential version windows.
    daily: dict[tuple[str, str], dict] = {}
    for row in predictions:
        key = (str(row.get("symbol") or ""), str(row.get("signal_date") or ""))
        if not all(key):
            continue
        previous = daily.get(key)
        if previous is None or _snapshot_key(row) > _snapshot_key(previous):
            daily[key] = row

    observations: list[Observation] = []
    for row in daily.values():
        outcome = outcome_by_id.get(row.get("pred_id"))
        if not outcome:
            continue
        factors = {
            factor: _number(row.get(f"trade_{factor}_norm"))
            for factor in FACTORS
        }
        if any(value is None for value in factors.values()):
            continue
        raw_gates = row.get("gates") if isinstance(row.get("gates"), dict) else {}
        gates = {factor: _number(raw_gates.get(factor)) for factor in FACTORS}
        if any(value is None for value in gates.values()):
            continue
        returns = {
            horizon: _number(outcome.get(f"ret_{horizon}d"))
            for horizon in HORIZONS
        }
        actual_score = _number(row.get("score_trade"))
        if actual_score is None:
            continue
        observations.append(
            Observation(
                date=str(row["signal_date"]),
                symbol=str(row["symbol"]),
                source_version=str(row["scoring_version"]),
                factors={key: float(value) for key, value in factors.items()},
                gates={key: float(value) for key, value in gates.items()},
                returns={key: float(value) for key, value in returns.items() if value is not None},
                actual_score=float(actual_score),
            )
        )
    return sorted(observations, key=lambda row: (row.date, row.symbol))


def composite_score(row: Observation, weights: dict[str, float]) -> float:
    return 100.0 * sum(
        weights[factor] * row.gates[factor] * row.factors[factor]
        for factor in FACTORS
    )


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    pos = 0
    while pos < len(order):
        end = pos + 1
        while end < len(order) and values[order[end]] == values[order[pos]]:
            end += 1
        rank = (pos + end - 1) / 2.0
        for idx in order[pos:end]:
            ranks[idx] = rank
        pos = end
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 5 or len(xs) != len(ys):
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    numerator = sum((x - mx) * (y - my) for x, y in zip(rx, ry))
    dx = math.sqrt(sum((x - mx) ** 2 for x in rx))
    dy = math.sqrt(sum((y - my) ** 2 for y in ry))
    return numerator / (dx * dy) if dx and dy else None


def bootstrap_mean_ci(values: list[float], seed: int = 417418) -> tuple[float, float]:
    if len(values) < 3:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    samples = sorted(
        statistics.fmean(rng.choice(values) for _ in values)
        for _ in range(5000)
    )
    return samples[int(0.025 * len(samples))], samples[int(0.975 * len(samples))]


def evaluate(
    observations: Iterable[Observation],
    weights: dict[str, float],
    horizon: int,
) -> dict:
    by_day: dict[str, list[Observation]] = defaultdict(list)
    for row in observations:
        if horizon in row.returns:
            by_day[row.date].append(row)

    day_ic: list[float] = []
    day_top_return: list[float] = []
    day_market_return: list[float] = []
    selected_returns: list[float] = []
    observations_n = 0
    for rows in by_day.values():
        if len(rows) < 5:
            continue
        scores = [composite_score(row, weights) for row in rows]
        returns = [row.returns[horizon] for row in rows]
        ic = spearman(scores, returns)
        if ic is not None:
            day_ic.append(ic)
        top_n = max(1, math.ceil(len(rows) * 0.20))
        selected = sorted(zip(scores, returns), reverse=True)[:top_n]
        top_returns = [ret for _, ret in selected]
        day_top_return.append(statistics.fmean(top_returns))
        day_market_return.append(statistics.fmean(returns))
        selected_returns.extend(top_returns)
        observations_n += len(rows)

    ic_ci = bootstrap_mean_ci(day_ic)
    excess_by_day = [top - market for top, market in zip(day_top_return, day_market_return)]
    excess_ci = bootstrap_mean_ci(excess_by_day, seed=418417)
    return {
        "days": len(day_top_return),
        "n": observations_n,
        "ic": statistics.fmean(day_ic) if day_ic else float("nan"),
        "ic_ci_low": ic_ci[0],
        "ic_ci_high": ic_ci[1],
        "top_return": statistics.fmean(day_top_return) if day_top_return else float("nan"),
        "market_return": statistics.fmean(day_market_return) if day_market_return else float("nan"),
        "excess": statistics.fmean(excess_by_day) if excess_by_day else float("nan"),
        "excess_ci_low": excess_ci[0],
        "excess_ci_high": excess_ci[1],
        "hit_rate": (
            100.0 * sum(value > 0 for value in selected_returns) / len(selected_returns)
            if selected_returns else float("nan")
        ),
    }



def reconstruction_check(observations: Iterable[Observation], version: str) -> dict:
    """Compare reconstructed core score with the ledger's full production score."""
    weights = WEIGHT_SETS[version]
    by_day: dict[str, list[Observation]] = defaultdict(list)
    errors: list[float] = []
    for row in observations:
        if row.source_version != version:
            continue
        by_day[row.date].append(row)
        errors.append(abs(composite_score(row, weights) - row.actual_score))
    day_rank_corr: list[float] = []
    for rows in by_day.values():
        corr = spearman(
            [composite_score(row, weights) for row in rows],
            [row.actual_score for row in rows],
        )
        if corr is not None:
            day_rank_corr.append(corr)
    return {
        "days": len(day_rank_corr),
        "rank_corr": statistics.fmean(day_rank_corr) if day_rank_corr else float("nan"),
        "mae": statistics.fmean(errors) if errors else float("nan"),
    }


def fmt(value: float, digits: int = 3) -> str:    return "—" if not math.isfinite(value) else f"{value:+.{digits}f}"


def markdown_report(observations: list[Observation]) -> str:
    dates = sorted({row.date for row in observations})
    holdout_n = max(3, math.ceil(len(dates) * 0.30)) if dates else 0
    holdout_dates = set(dates[-holdout_n:])
    windows = {
        "Toàn kỳ": observations,
        "30% ngày mới nhất (pseudo-OOS)": [row for row in observations if row.date in holdout_dates],
    }
    source_counts = defaultdict(int)
    for row in observations:
        source_counts[row.source_version] += 1

    lines = [
        "# Backtest hybrid factor v4.17/v4.18",
        "",
        f"**Tạo lúc:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Dữ liệu:** {dates[0] if dates else '—'} → {dates[-1] if dates else '—'}; "
        f"{len(dates)} ngày tín hiệu; {len(observations):,} mã-ngày đã join outcome.",
        "",
        "## Candidate được kiểm định",
        "",
        "- Mean Reversion và Flow: chọn từ v4.17.",
        "- Breakout, Fundamental và Growth: chọn từ v4.18.",
        "- Kiểm tra source cho thấy v4.18 chỉ đổi trọng số TRADE so với v4.17; công thức/cap của 5 factor không đổi. "
        "Vì vậy lựa chọn source không tạo giá trị factor mới. Candidate có thể kiểm định là cách ghép trọng số.",
        "- `hybrid_equal`: 20% cho mỗi factor; score dùng factor norm × regime gate, không dùng bonus/extras.",
        "- Sensitivity `hybrid_no_mr`: MR=0%, bốn factor còn lại 25%; đây là chẩn đoán sau khi xem dữ liệu, không phải candidate đăng ký trước.",
        "",
        "Đối chứng: trọng số production v4.17 và v4.18 được áp lại trên cùng toàn bộ quan sát.",
        "",
        "## Kết quả",
        "",
    ]
    for window_name, window_rows in windows.items():
        window_dates = sorted({row.date for row in window_rows})
        lines.extend([
            f"### {window_name}",
            "",
            f"Khoảng ngày: {window_dates[0] if window_dates else '—'} → "
            f"{window_dates[-1] if window_dates else '—'} ({len(window_dates)} ngày).",
            "",
            "| Horizon | Model | Daily IC | 95% CI IC | Top 20% return | Market | Excess | 95% CI excess | Hit rate | n |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for horizon in HORIZONS:
            for model, weights in WEIGHT_SETS.items():
                result = evaluate(window_rows, weights, horizon)
                lines.append(
                    f"| {horizon}d | {model} | {fmt(result['ic'])} | "
                    f"[{fmt(result['ic_ci_low'])}, {fmt(result['ic_ci_high'])}] | "
                    f"{fmt(result['top_return'], 2)}% | {fmt(result['market_return'], 2)}% | "
                    f"{fmt(result['excess'], 2)}% | "
                    f"[{fmt(result['excess_ci_low'], 2)}, {fmt(result['excess_ci_high'], 2)}]% | "
                    f"{result['hit_rate']:.1f}% | {result['n']:,} |"
                )
        lines.append("")

    lines.extend([
        "## Chẩn đoán từng factor",
        "",
        "Daily IC của từng factor sau regime gate, tính trên cùng cửa sổ pooled. "
        "Bảng này giúp phân biệt hiệu quả do ghép trọng số với hiệu quả do tên version.",
        "",
        "| Horizon | Factor | IC toàn kỳ | 95% CI | IC 30% ngày mới nhất | 95% CI |",
        "|---:|---|---:|---:|---:|---:|",
    ])
    holdout_rows = windows["30% ngày mới nhất (pseudo-OOS)"]
    for horizon in HORIZONS:
        for factor in FACTORS:
            one_factor = {name: 1.0 if name == factor else 0.0 for name in FACTORS}
            full_result = evaluate(observations, one_factor, horizon)
            holdout_result = evaluate(holdout_rows, one_factor, horizon)
            lines.append(
                f"| {horizon}d | {factor} | {fmt(full_result['ic'])} | "
                f"[{fmt(full_result['ic_ci_low'])}, {fmt(full_result['ic_ci_high'])}] | "
                f"{fmt(holdout_result['ic'])} | "
                f"[{fmt(holdout_result['ic_ci_low'])}, {fmt(holdout_result['ic_ci_high'])}] |"
            )

    lines.extend([
        "",
        "## Kiểm tra tái dựng score",
        "",
        "Score đối chứng được tái dựng từ factor norm × gate × weight. Ledger score thật còn có "
        "confluence/flow extras, nên MAE không bằng 0; daily rank correlation cần ở mức rất cao.",
        "",
        "| Version | Số ngày | Daily rank correlation với score thật | MAE score |",
        "|---|---:|---:|---:|",
    ])
    for version in ("v4.17", "v4.18"):
        check = reconstruction_check(observations, version)
        lines.append(
            f"| {version} | {check['days']} | {check['rank_corr']:.4f} | {check['mae']:.2f} |"
        )

    full_h5 = {
        model: evaluate(observations, weights, 5)
        for model, weights in WEIGHT_SETS.items()
    }
    holdout_h5 = {
        model: evaluate(holdout_rows, weights, 5)
        for model, weights in WEIGHT_SETS.items()
    }
    lines.extend([
        "",
        "## Kết luận",
        "",
        f"- `hybrid_equal` vượt hai đối chứng production ở 5d: IC {full_h5['hybrid_equal']['ic']:+.3f} và excess "
        f"{full_h5['hybrid_equal']['excess']:+.2f}% toàn kỳ; ở 30% ngày mới nhất là IC "
        f"{holdout_h5['hybrid_equal']['ic']:+.3f} và excess {holdout_h5['hybrid_equal']['excess']:+.2f}%.",
        "- Candidate thắng về xếp hạng tương đối nhưng top 20% vẫn có return âm trong giai đoạn thị trường giảm. "
        "Không nên diễn giải đây là chiến lược tạo lợi nhuận tuyệt đối.",
        "- `hybrid_no_mr` chỉ là sensitivity được hình thành sau khi nhìn kết quả, nên có selection bias và không được dùng để tuyên bố thắng ngoài mẫu.",
        "- Kết quả ủng hộ chạy shadow `hybrid_equal`; chưa đủ bằng chứng để thay production trước khi có ít nhất 30 ngày outcome chín độc lập.",
        "",
    ])

    lines.extend([
        "## Cách đọc và giới hạn",
        "",
        "- IC là Spearman theo từng ngày rồi mới lấy trung bình; CI bootstrap theo ngày, tránh coi các mã trong cùng ngày là độc lập.",
        "- Top 20% là danh mục xếp hạng cao nhất mỗi ngày. Return và excess là trung bình đều theo ngày, chưa trừ phí.",
        "- `pseudo-OOS` chỉ là đoạn thời gian mới nhất, không phải out-of-sample hoàn toàn vì ý tưởng chọn factor xuất phát từ IC đã quan sát.",
        "- Số ngày còn ngắn; không dùng kết quả này để tự động thay production. Candidate chỉ nên chạy shadow cho tới khi có ít nhất 30 ngày chín độc lập.",
        "- Ledger giữ Flow và fundamental tại thời điểm tín hiệu; đây là lợi thế so với replay OHLC bị trung hòa Flow hoặc dùng fundamental hiện tại.",
        "",
        "## Truy xuất nguồn",
        "",
        f"- v4.17: {source_counts['v4.17']:,} mã-ngày.",
        f"- v4.18: {source_counts['v4.18']:,} mã-ngày.",
        "- Predictions: `output/history/v2f_predictions_v4/*.jsonl`.",
        "- Outcomes: `output/history/v2f_outcomes_v4/*.jsonl`.",
        "- Script: `backtest/backtest_hybrid_v417_v418.py`.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(ROOT / "docs/HYBRID_BACKTEST_V417_V418.md"),
        help="Markdown report path",
    )
    args = parser.parse_args()
    observations = build_observations()
    if not observations:
        raise SystemExit("No joined v4.17/v4.18 observations found.")
    report = markdown_report(observations)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(report.encode("utf-8"))
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
