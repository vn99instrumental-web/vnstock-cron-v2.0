"""Independent generation-6 SSI OHLC, technical scoring, ledger and outcomes.

Historical generation-4/5 ledgers remain immutable. New records are written only
under output/history/vnstock6 and carry explicit generation/source provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from vnstock import Market, Reference
from vnstock.errors import VnstockError

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "vnstock6.json"
PRED_ROOT = ROOT / "output" / "history" / "vnstock6" / "predictions"
OUTCOME_ROOT = ROOT / "output" / "history" / "vnstock6" / "outcomes"
OHLC_ROOT = ROOT / "output" / "ohlc"
ICT = timezone(timedelta(hours=7))


def load_config() -> dict[str, Any]:
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if value.get("source") != "SSI" or not value.get("universe"):
        raise ValueError("VNStock6 config must declare the user-selected SSI source and universe")
    return value


def finite(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def normalize_ohlcv(frame: pd.DataFrame, symbol: str) -> list[dict[str, Any]]:
    data = frame.reset_index()
    lowered = {str(column).lower(): column for column in data.columns}
    time_column = next((lowered[key] for key in ("time", "date", "datetime", "index") if key in lowered), None)
    required = {name: lowered.get(name) for name in ("open", "high", "low", "close", "volume")}
    if time_column is None or any(column is None for column in required.values()):
        raise ValueError(f"SSI OHLC schema unsupported for {symbol}: {list(data.columns)}")
    rows: dict[str, dict[str, Any]] = {}
    for _, source in data.iterrows():
        parsed = pd.to_datetime(source[time_column], errors="coerce")
        if pd.isna(parsed):
            continue
        day = parsed.date().isoformat()
        row = {"symbol": symbol, "date": day, "market_source": "SSI", "pipeline_generation": 6}
        for name, column in required.items():
            row[name] = finite(source[column])
        if all(row[name] is not None for name in ("open", "high", "low", "close")):
            rows[day] = row
    return [rows[key] for key in sorted(rows)]


def merge_ohlcv(symbol: str, incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    path = OHLC_ROOT / f"{symbol}.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    merged = {str(row.get("date")): row for row in existing if row.get("date")}
    merged.update({row["date"]: row for row in incoming})
    result = [merged[key] for key in sorted(merged)][-900:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return result


def rsi(series: pd.Series, periods: int = 14) -> float | None:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(periods).mean()
    loss = -delta.clip(upper=0).rolling(periods).mean()
    denominator = loss.iloc[-1]
    if pd.isna(denominator):
        return None
    if denominator == 0:
        return 100.0
    return finite(100 - (100 / (1 + gain.iloc[-1] / denominator)))


def score(symbol: str, rows: list[dict[str, Any]], version: str, snap_time: str) -> dict[str, Any]:
    frame = pd.DataFrame(rows).sort_values("date")
    if len(frame) < 50:
        raise ValueError(f"Insufficient OHLC history for {symbol}: {len(frame)}")
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    latest = frame.iloc[-1]
    ema20 = finite(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = finite(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ema200 = finite(close.ewm(span=200, adjust=False).mean().iloc[-1]) if len(frame) >= 200 else None
    current = finite(latest["close"])
    rsi14 = rsi(close)
    return20 = finite((current / close.iloc[-21] - 1) * 100) if len(frame) >= 21 and current else None
    vol_ratio = finite(volume.iloc[-1] / volume.tail(20).mean())
    high52 = finite(pd.to_numeric(frame["high"], errors="coerce").tail(252).max())
    low52 = finite(pd.to_numeric(frame["low"], errors="coerce").tail(252).min())
    trend = (20 if current and ema20 and current > ema20 else -20) + (15 if ema20 and ema50 and ema20 > ema50 else -15)
    momentum = 0 if rsi14 is None else (15 if 45 <= rsi14 <= 70 else -12 if rsi14 > 75 else 10 if rsi14 < 30 else 0)
    breakout = 15 if return20 is not None and return20 > 5 else -15 if return20 is not None and return20 < -5 else 0
    liquidity = 5 if vol_ratio is not None and vol_ratio >= 1.2 else -5 if vol_ratio is not None and vol_ratio < 0.5 else 0
    total = round(max(-100, min(100, trend + momentum + breakout + liquidity)), 2)
    decision = "STRONG BUY" if total >= 55 else "BUY" if total >= 25 else "STRONG SELL" if total <= -55 else "SELL" if total <= -25 else "NEUTRAL"
    signal_date = str(latest["date"])
    raw_id = f"6|SSI|{symbol}|{signal_date}|{snap_time}|{version}"
    pred_id = f"v6_{hashlib.sha256(raw_id.encode()).hexdigest()[:24]}"
    return {
        "pred_id": pred_id, "symbol": symbol, "signal_date": signal_date, "snap_time": snap_time,
        "scoring_version": version, "decision": decision, "score_trade": total, "total_score": total,
        "price": current, "confidence": "HIGH" if abs(total) >= 55 else "MEDIUM" if abs(total) >= 25 else "LOW",
        "pipeline_generation": 6, "market_source": "SSI", "data_origin": "native",
        "flow": "vnstock6_native", "universe_variant": "vn100-cutover", "registry_version": 1,
        "ema20": ema20, "ema50": ema50, "ema200": ema200, "rsi_14": rsi14,
        "return_20d": return20, "vol_ma_ratio": vol_ratio, "high_52w": high52, "low_52w": low52,
        "s_trend_st": trend, "s_momentum_native": momentum, "s_breakout_native": breakout,
        "s_volume_native": liquidity, "fundamental_status": "unavailable_in_gen6_community",
    }


def append_jsonl(path: Path, rows: list[dict[str, Any]], key: str) -> int:
    existing: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                existing[str(item.get(key))] = item
    before = len(existing)
    existing.update({str(row[key]): row for row in rows})
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in existing.values())
    path.write_text(body, encoding="utf-8")
    return len(existing) - before


def run_native(config: dict[str, Any], force: bool) -> None:
    today = date.today()
    if today.isoformat() < config["cutover_date"] and not force:
        raise RuntimeError("VNStock6 cutover date has not been reached")
    reference = Reference("ssi").equity.list()
    available = {str(value).upper() for value in reference["symbol"].dropna()}
    universe = [symbol for symbol in config["universe"] if symbol in available]
    start = (today - timedelta(days=int(config["history_days"]))).isoformat()
    now = datetime.now(ICT)
    predictions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for symbol in universe:
        try:
            frame = Market("ssi").equity(symbol).ohlcv(start=start)
            merged = merge_ohlcv(symbol, normalize_ohlcv(frame, symbol))
            predictions.append(score(symbol, merged, config["scoring_version"], now.strftime("%H:%M")))
        except (VnstockError, ValueError, KeyError) as exc:
            errors.append({"symbol": symbol, "type": type(exc).__name__, "code": getattr(exc, "code", None)})
    if len(predictions) < int(config["minimum_coverage"]):
        raise RuntimeError(f"VNStock6 coverage {len(predictions)}/{len(universe)} below minimum; errors={errors[:10]}")
    partition = PRED_ROOT / f"{predictions[0]['signal_date']}.jsonl"
    added = append_jsonl(partition, predictions, "pred_id")
    status = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "source": "SSI",
        "scoring_version": config["scoring_version"], "universe_size": len(universe),
        "successful_symbols": len(predictions), "failed_symbols": errors, "records_added": added,
    }
    status_path = ROOT / "output" / "vnstock6" / "native-status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"VNStock6 native: {len(predictions)}/{len(universe)} symbols, {added} new predictions")


def evaluate(config: dict[str, Any]) -> None:
    predictions = []
    for path in sorted(PRED_ROOT.glob("*.jsonl")):
        predictions.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    outcomes: list[dict[str, Any]] = []
    for prediction in predictions:
        bars = json.loads((OHLC_ROOT / f"{prediction['symbol']}.json").read_text(encoding="utf-8"))
        later = [row for row in bars if str(row.get("date")) > prediction["signal_date"]]
        entry = finite(prediction.get("price"))
        if not entry or not later:
            continue
        row = {"pred_id": prediction["pred_id"], "symbol": prediction["symbol"], "scoring_version": config["scoring_version"], "lens": "trade", "pipeline_generation": 6, "market_source": "SSI", "n_bars": len(later), "eval_date": later[-1]["date"]}
        for horizon in (1, 3, 5, 10):
            row[f"ret_{horizon}d"] = round((float(later[horizon - 1]["close"]) / entry - 1) * 100, 6) if len(later) >= horizon else None
        outcomes.append(row)
    if outcomes:
        by_month: dict[str, list[dict[str, Any]]] = {}
        for row in outcomes:
            by_month.setdefault(str(row["eval_date"])[:7], []).append(row)
        for month, rows in by_month.items():
            append_jsonl(OUTCOME_ROOT / f"{month}.jsonl", rows, "pred_id")
    print(f"VNStock6 outcomes updated: {len(outcomes)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "evaluate"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    config = load_config()
    run_native(config, args.force) if args.command == "run" else evaluate(config)


if __name__ == "__main__":
    main()
