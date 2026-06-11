"""
step_scoring_v2.py — Scoring engine v2 (Weighted Normalized, parallel với v3)
==============================================================================
Chạy SONG SONG với step_scoring.py (v3). KHÔNG thay thế v3.

THAY ĐỔI SO VỚI V3:
  1. Normalize từng group về [-1, +1]: score_norm = raw_score / cap
  2. Weighted sum → total_score ∈ [-100, +100]
  3. Weight phản ánh IC thực tế T+30 thị trường VN (technical dominant)
  4. Fundamental/CF/Growth vẫn có score 2 chiều đầy đủ — weight nhỏ hơn
  5. Threshold mới: ≥50 STRONG BUY | ≥25 BUY | ≥-10 NEUTRAL | ≥-25 SELL
  6. Output: signals_v2.json / signals_v2.csv

KHÔNG THAY ĐỔI SO VỚI V3:
  - Toàn bộ indicator logic (EMA, RSI, MACD, CMF, FF, Fundamental...)
  - Sector-aware rules (CF skip, D/E skip)
  - Order flow integration
  - Depth scoring
  - News scoring
  - Confluence bonus (tính ngoài weighted sum, cộng thêm)
  - Phase 2.11 sign calibration (mean-reversion VN)

WEIGHT RATIONALE (horizon ≤30 ngày):
  Technical bucket (58%): IC cao nhất T+5→T+30
  FF + Smart Money (20%): leading 5–15 ngày
  Context + News   ( 8%): bối cảnh, decay nhưng vẫn valid
  Fund + CF + Growth (14%): IC thấp T+30 nhưng không bằng 0 — vẫn tính

SCORING_VERSION = "v2"
  → Predictions ghi vào history/predictions/ với version riêng
  → Backtest v3 và v2 phân tách hoàn toàn

CHANGELOG:
  2026-06-11 — v2 initial: normalized weighted scoring, parallel với v3
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"

import logging
import pandas as pd

from utils.helpers import now_ict, today_str
from utils.cache   import load_json, save_json, save_csv, save_display_csv
from utils.formatter import clean_for_export
from utils.indicators_meta import INDICATORS_META

# Import toàn bộ logic từ v3 — không duplicate code
from steps.step_scoring import (
    SECTOR_CF_SKIP_SIGN,
    SECTOR_SKIP_DE,
    _is_sector_match,
    build_news_scores,
    score_order_flow,
    _ob_valid,
    WALL_MIN_VOL,
    score_depth,
    score_symbol as _score_symbol_v3,   # dùng để lấy raw group scores
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# V2 CONFIG
# =====================================================

SCORING_VERSION = "v2"

# Cap cho từng group (giữ nguyên v3)
GROUP_CAPS = {
    "trend":       30,
    "momentum":    23,
    "volume":      20,
    "volatility":  5,
    "order_flow":  10,
    "depth":       5,
    "ff":          20,
    "fundamental": 20,
    "cf":          10,
    "growth":      10,
    "context":     5,
    "news":        5,
}

# Weight phân bổ (tổng = 1.00)
# Horizon ≤30 ngày — technical dominant, fundamental nhỏ nhưng không bỏ
SCORING_WEIGHTS = {
    "trend":       0.20,   # nền tảng (+0.02 tạm từ smart_money placeholder)
    "momentum":    0.14,   # driver chính T+5→T+15
    "volume":      0.10,   # xác nhận momentum
    "order_flow":  0.08,   # IC cao nhưng decay sau T+10
    "volatility":  0.04,   # nhỏ nhưng independent
    "depth":       0.04,   # intraday, decay nhanh
    "ff":          0.18,   # consistent T+5→T+30 (+0.06 tạm từ smart_money placeholder)
    # smart_money (prop+insider): Phase B — khi có: trend=0.18, ff=0.12, smart_money=0.08
    "context":     0.04,   # macro background
    "news":        0.04,   # decay nhanh nhưng có signal
    "fundamental": 0.06,   # IC thấp T+30 nhưng không bằng 0
    "cf":          0.04,   # quality signal nhẹ
    "growth":      0.04,   # lag nhất nhưng vẫn đóng góp
}
# Tổng = 1.00: 0.20+0.14+0.10+0.08+0.04+0.04+0.18+0.04+0.04+0.06+0.04+0.04
# Kiểm tra tổng = 1.00
assert abs(sum(SCORING_WEIGHTS.values()) - 1.0) < 1e-9, \
    f"Weights sum = {sum(SCORING_WEIGHTS.values()):.4f} ≠ 1.0"

# Confluence bonus vẫn cộng ngoài weighted sum (±10)
CONFLUENCE_THRESHOLD_PCT = 0.30   # ≥30% cap = meaningful signal

# Thresholds mới cho scale ±100
THRESHOLD_STRONG_BUY  =  50
THRESHOLD_BUY         =  25
THRESHOLD_NEUTRAL     = -10
THRESHOLD_SELL        = -25
# STRONG SELL: < -25

# =====================================================
# NORMALIZE + WEIGHT
# =====================================================

def _normalize_and_weight(raw_scores: dict) -> tuple[float, dict]:
    """
    Normalize từng group về [-1, +1], tính weighted sum.
    Returns:
        weighted_score: float ∈ [-100, +100] (trước confluence)
        norm_scores:    dict group → float ∈ [-1, +1]
    """
    norm = {}
    for g, cap in GROUP_CAPS.items():
        raw = raw_scores.get(g, 0)
        norm[g] = max(-1.0, min(1.0, raw / cap))

    weighted_sum = sum(
        SCORING_WEIGHTS.get(g, 0) * norm[g]
        for g in SCORING_WEIGHTS
    )
    return round(weighted_sum * 100, 2), norm


def _confluence_bonus(norm_scores: dict) -> tuple[int, str]:
    """
    Tính confluence bonus dựa trên normalized scores.
    Group "meaningful" khi |norm| >= CONFLUENCE_THRESHOLD_PCT.
    Bỏ qua context (macro-only).
    """
    check_groups = {k: v for k, v in norm_scores.items() if k != "context"}

    positive = sum(
        1 for g, n in check_groups.items()
        if n >= CONFLUENCE_THRESHOLD_PCT
    )
    negative = sum(
        1 for g, n in check_groups.items()
        if n <= -CONFLUENCE_THRESHOLD_PCT
    )

    n_groups = len(check_groups)  # 11 groups (không có context)

    bonus = 0
    label = ""
    if positive >= 7:
        bonus =  10
        label = f"CONFLUENCE strong bull ({positive}/{n_groups} groups)"
    elif positive >= 5:
        bonus =  5
        label = f"CONFLUENCE bull ({positive}/{n_groups} groups)"
    elif negative >= 7:
        bonus = -10
        label = f"CONFLUENCE strong bear ({negative}/{n_groups} groups)"
    elif negative >= 5:
        bonus = -5
        label = f"CONFLUENCE bear ({negative}/{n_groups} groups)"

    return bonus, label


def _decision(total: float) -> str:
    if   total >= THRESHOLD_STRONG_BUY: return "STRONG BUY"
    elif total >= THRESHOLD_BUY:        return "BUY"
    elif total >= THRESHOLD_NEUTRAL:    return "NEUTRAL"
    elif total >= THRESHOLD_SELL:       return "SELL"
    else:                               return "STRONG SELL"


# =====================================================
# SCORE SYMBOL V2
# =====================================================

def score_symbol_v2(row: dict, context: dict, news_scores: dict,
                    order_flow_map: dict) -> dict:
    """
    Gọi v3 để lấy raw group scores, sau đó:
    1. Normalize từng group về [-1, +1]
    2. Weighted sum → base_score ∈ [-100, +100]
    3. Cộng confluence bonus → final_score
    4. Assign decision theo threshold v2
    """
    # ── Gọi v3 scorer để lấy toàn bộ raw scores + signals ──
    v3_result = _score_symbol_v3(row, context, news_scores, order_flow_map)

    # ── Lấy raw group scores từ v3 result ──
    raw_scores = {
        "trend":       v3_result.get("trend_score",       0),
        "momentum":    v3_result.get("momentum_score",    0),
        "volume":      v3_result.get("volume_score",      0),
        "volatility":  v3_result.get("volatility_score",  0),
        "order_flow":  v3_result.get("order_flow_score",  0),
        "depth":       v3_result.get("depth_score",       0),
        "ff":          v3_result.get("ff_score",          0),
        "fundamental": v3_result.get("fundamental_score", 0),
        "cf":          v3_result.get("cf_score",          0),
        "growth":      v3_result.get("growth_score",      0),
        "context":     v3_result.get("context_score",     0),
        "news":        v3_result.get("news_score",        0),
    }

    # ── Normalize + weighted sum ──
    base_score, norm_scores = _normalize_and_weight(raw_scores)

    # ── Confluence bonus (dùng normalized scores) ──
    confluence_bonus, confluence_label = _confluence_bonus(norm_scores)

    # Thêm confluence vào signals nếu có
    if confluence_bonus != 0:
        sigs = v3_result.get("signals", "")
        extra = f"{confluence_label} {'+' if confluence_bonus > 0 else ''}{confluence_bonus}"
        v3_result["signals"] = (sigs + " | " + extra) if sigs else extra

    # ── Final score ──
    total_score = round(base_score + confluence_bonus, 2)

    # ── Decision v2 ──
    decision_v2 = _decision(total_score)

    # ── Tech/Fund scores (dùng raw, cùng logic v3) ──
    tech_score = (raw_scores["trend"] + raw_scores["momentum"] +
                  raw_scores["volume"] + raw_scores["volatility"] +
                  raw_scores["order_flow"])
    fund_score = (raw_scores["fundamental"] + raw_scores["cf"] +
                  raw_scores["growth"])

    # ── Pattern flags (giữ nguyên logic v3) ──
    pattern_flags = []
    confidence = "MEDIUM"

    if tech_score >= 40 and fund_score <= -15:
        pattern_flags.append("BULL_TRAP_RISK")
        confidence = "LOW"
    elif tech_score <= -30 and fund_score >= 15:
        pattern_flags.append("VALUE_OPPORTUNITY")
        confidence = "MEDIUM"
    elif tech_score >= 30 and fund_score >= 15:
        pattern_flags.append("CONSENSUS_BULL")
        confidence = "HIGH"
    elif tech_score <= -30 and fund_score <= -15:
        pattern_flags.append("CONSENSUS_BEAR")
        confidence = "HIGH"
    elif abs(tech_score) < 20 and abs(fund_score) < 10:
        pattern_flags.append("UNCLEAR")
        confidence = "LOW"

    # ── Build output — copy v3 result + override v2 fields ──
    out = dict(v3_result)

    # Override scoring fields
    out["total_score"]      = total_score
    out["base_score_v2"]    = base_score          # weighted sum trước confluence
    out["confluence_bonus"] = confluence_bonus
    out["decision"]         = decision_v2
    out["confidence"]       = confidence
    out["pattern_flags"]    = pattern_flags
    out["scoring_version"]  = SCORING_VERSION
    out["tech_score"]       = tech_score
    out["fund_score"]       = fund_score

    # Normalized scores (debug/audit)
    out["norm_trend"]       = round(norm_scores.get("trend",       0), 4)
    out["norm_momentum"]    = round(norm_scores.get("momentum",    0), 4)
    out["norm_volume"]      = round(norm_scores.get("volume",      0), 4)
    out["norm_volatility"]  = round(norm_scores.get("volatility",  0), 4)
    out["norm_order_flow"]  = round(norm_scores.get("order_flow",  0), 4)
    out["norm_depth"]       = round(norm_scores.get("depth",       0), 4)
    out["norm_ff"]          = round(norm_scores.get("ff",          0), 4)
    out["norm_fundamental"] = round(norm_scores.get("fundamental", 0), 4)
    out["norm_cf"]          = round(norm_scores.get("cf",          0), 4)
    out["norm_growth"]      = round(norm_scores.get("growth",      0), 4)
    out["norm_context"]     = round(norm_scores.get("context",     0), 4)
    out["norm_news"]        = round(norm_scores.get("news",        0), 4)

    # Weight snapshot (để debug sau khi IC update)
    out["w_trend"]       = SCORING_WEIGHTS["trend"]
    out["w_momentum"]    = SCORING_WEIGHTS["momentum"]
    out["w_volume"]      = SCORING_WEIGHTS["volume"]
    out["w_order_flow"]  = SCORING_WEIGHTS["order_flow"]
    out["w_ff"]          = SCORING_WEIGHTS["ff"]
    out["w_fundamental"] = SCORING_WEIGHTS["fundamental"]
    out["w_cf"]          = SCORING_WEIGHTS["cf"]
    out["w_growth"]      = SCORING_WEIGHTS["growth"]

    return out


# =====================================================
# MAIN
# =====================================================

def run():
    log.info(f"=== SCORING V2 START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    log.info(f"Scoring version: {SCORING_VERSION}")
    log.info(f"Thresholds: SB≥{THRESHOLD_STRONG_BUY} | "
             f"BUY≥{THRESHOLD_BUY} | "
             f"NEU≥{THRESHOLD_NEUTRAL} | "
             f"SELL≥{THRESHOLD_SELL} | SS<{THRESHOLD_SELL}")

    # ── Load inputs (cùng file với v3) ──
    deep_raw   = load_json("deep_raw.json")
    context_list = load_json("market/context.json") or load_json("context.json")
    today_index  = load_json("news/today_index.json") or \
                   load_json("news_today_index.json")
    order_flow   = load_json("order_flow.json")

    if not deep_raw:
        log.error("deep_raw.json not found — abort")
        return

    ctx = context_list[0] if context_list else {}

    if today_index is None:
        log.warning("news_today_index.json not found — news_score = 0")

    if order_flow is None:
        log.warning("order_flow.json not found — order_flow_score = 0")
        order_flow = []

    # Build order_flow map
    order_flow_map = {}
    if isinstance(order_flow, list):
        for r in order_flow:
            if isinstance(r, dict) and r.get("symbol"):
                order_flow_map[r["symbol"]] = r

    # Build news scores
    symbols_with_industry = [
        {"symbol": r["symbol"], "icb_name": r.get("industry", "")}
        for r in deep_raw
    ]
    news_scores = build_news_scores(today_index or {}, symbols_with_industry)

    log.info(f"Scoring {len(deep_raw)} symbols with v2 weights...")

    scored_rows = []
    for row in deep_raw:
        result = score_symbol_v2(row, ctx, news_scores, order_flow_map)
        scored_rows.append(result)

        flags_str = ",".join(result.get("pattern_flags", [])) or "-"
        log.info(
            f"  [{result['symbol']}] "
            f"v2={result['total_score']:.1f} "
            f"(base={result['base_score_v2']:.1f} "
            f"conf={result['confluence_bonus']:+d}) "
            f"→ {result['decision']} [{result['confidence']}] [{flags_str}]"
        )

    df = pd.DataFrame(scored_rows)

    # ── Save signals_v2.json ──
    save_json("signals_v2.json", df.to_dict(orient="records"))

    # ── Save signals_v2.csv ──
    news_evidence_col = df["news_evidence"].apply(
        lambda evs: " | ".join(
            f"{e.get('type','?')}·{e.get('source','?')}·"
            f"{e.get('title','')[:40]}·"
            f"{str(e.get('time',''))[5:16]}·"
            f"{e.get('contribution', 0):+.2f}"
            for e in (evs or [])
        )
    ) if "news_evidence" in df.columns else pd.Series([""] * len(df))

    pattern_flags_col = df["pattern_flags"].apply(
        lambda f: ",".join(f or [])
    ) if "pattern_flags" in df.columns else pd.Series([""] * len(df))

    df_csv = df.drop(
        columns=["news_evidence", "_ohlcv_5d", "pattern_flags"],
        errors="ignore"
    )
    df_csv = clean_for_export(df_csv)
    df_csv["news_evidence"] = news_evidence_col.values
    df_csv["pattern_flags"] = pattern_flags_col.values
    save_csv("signals_v2.csv", df_csv)

    # ── Decision distribution log ──
    decision_counts   = df["decision"].value_counts().to_dict()
    confidence_counts = df["confidence"].value_counts().to_dict()

    # So sánh với v3 nếu có
    v3_signals = load_json("signals.json")
    if v3_signals:
        v3_df = pd.DataFrame(v3_signals)[["symbol", "decision", "total_score"]]
        v3_df.columns = ["symbol", "decision_v3", "score_v3"]
        v2_df = df[["symbol", "decision", "total_score"]].copy()
        v2_df.columns = ["symbol", "decision_v2", "score_v2"]
        compare = pd.merge(v3_df, v2_df, on="symbol", how="inner")
        agree = (compare["decision_v3"] == compare["decision_v2"]).sum()
        total = len(compare)
        log.info(f"V3 vs V2 agreement: {agree}/{total} = {agree/total*100:.1f}%")

        # Log mã có decision khác nhau
        diff = compare[compare["decision_v3"] != compare["decision_v2"]]
        if not diff.empty:
            log.info(f"Decision diff ({len(diff)} symbols):")
            for _, r in diff.iterrows():
                log.info(
                    f"  {r.symbol}: v3={r.decision_v3}({r.score_v3:.0f}) "
                    f"→ v2={r.decision_v2}({r.score_v2:.1f})"
                )

    log.info(f"V2 Decision distribution: {decision_counts}")
    log.info(f"V2 Confidence distribution: {confidence_counts}")
    log.info(f"Exported signals_v2.json + signals_v2.csv ({len(df)} rows)")
    log.info("=== SCORING V2 DONE ===")


if __name__ == "__main__":
    run()
