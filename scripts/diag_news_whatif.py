# scripts/diag_news_whatif.py
# ============================================================================
# WHAT-IF (READ-ONLY): nếu áp news_score vào scoring V2.3 thì total_score
# và decision của ~130 mã thay đổi thế nào?
#
# KHÔNG đụng production:
#   - Chỉ ĐỌC output/v2f_signals.json + output/news/today_index.json
#   - Import hằng số ngưỡng từ v2f_step_scoring (read-only) để mô phỏng
#     đúng thresholds thật — không sửa, không ghi file nào
#   - Chạy qua debug.yml (không có bước commit) → repo nguyên vẹn
#
# 3 kịch bản mô phỏng:
#   S1 ADDITIVE : new_total = total + news_score            (±5 trên thang ±100)
#   S2 WEIGHT 3%: new_total = total×0.97 + 3×(news/5)       (news thành nhóm 3%)
#   S3 WEIGHT 5%: new_total = total×0.95 + 5×(news/5)
#
# Chạy: debug.yml → script = scripts/diag_news_whatif.py
# ============================================================================
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("VNSTOCK_INTERACTIVE", "0")
os.environ.setdefault("MPLCONFIGDIR", "/home/runner/.config/matplotlib")

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger("news_whatif")

from utils.cache import load_json

# Ngưỡng decision THẬT của V2.3 — import read-only từ module production
try:
    from steps.v2f_step_scoring import (
        THRESHOLD_STRONG_BUY, THRESHOLD_BUY,
        THRESHOLD_NEUTRAL, THRESHOLD_SELL,
    )
    _THRESH_SRC = "v2f_step_scoring (import)"
except Exception as e:
    log.warning(f"Không import được thresholds từ v2f_step_scoring ({e}) "
                f"— dùng fallback. KIỂM TRA LẠI nếu số flip bất thường.")
    THRESHOLD_STRONG_BUY, THRESHOLD_BUY = 55, 25
    THRESHOLD_NEUTRAL, THRESHOLD_SELL   = -15, -35
    _THRESH_SRC = "fallback hardcode"


def _decision(total: float) -> str:
    if   total >= THRESHOLD_STRONG_BUY: return "STRONG BUY"
    elif total >= THRESHOLD_BUY:        return "BUY"
    elif total >= THRESHOLD_NEUTRAL:    return "NEUTRAL"
    elif total >= THRESHOLD_SELL:       return "SELL"
    else:                               return "STRONG SELL"


def _decode_news(idx: dict, sym: str, industry: str) -> tuple[float, float, float, float]:
    """Decode news_score theo đúng công thức build_news_scores của consumer."""
    ind_c = float(idx.get("by_industry", {}).get(industry, {}).get("score", 2.0)) - 2.0
    sym_c = float(idx.get("symbol_mentions", {}).get(sym, {}).get("score", 2.0)) - 2.0
    mac_c = float(idx.get("macro", {}).get("score", 1.0)) - 1.0
    total = max(-5.0, min(5.0, round(ind_c + sym_c + mac_c, 2)))
    return total, sym_c, ind_c, mac_c


SCENARIOS = [
    ("S1_ADDITIVE",  lambda t, n: t + n),
    ("S2_WEIGHT_3%", lambda t, n: t * 0.97 + 3.0 * (n / 5.0)),
    ("S3_WEIGHT_5%", lambda t, n: t * 0.95 + 5.0 * (n / 5.0)),
]


def run():
    signals = load_json("v2f_signals.json") or []
    idx     = load_json("news/today_index.json") or load_json("news_today_index.json") or {}

    if not signals:
        log.error("v2f_signals.json không có — cần ít nhất 1 run intraday trước")
        return 1
    if not idx:
        log.error("news/today_index.json không có — cần cron_news chạy trước")
        return 1

    gen = idx.get("generated_at", "?")
    log.info(f"=== NEWS WHAT-IF (read-only) ===")
    log.info(f"Signals: {len(signals)} mã | News index generated_at: {gen} "
             f"(schema {idx.get('schema', 1)})")
    log.info(f"Thresholds nguồn: {_THRESH_SRC} "
             f"(SB≥{THRESHOLD_STRONG_BUY} BUY≥{THRESHOLD_BUY} "
             f"NEU≥{THRESHOLD_NEUTRAL} SELL≥{THRESHOLD_SELL})")

    rows = []
    for r in signals:
        sym = r.get("symbol")
        if not sym:
            continue
        total = r.get("total_score")
        if total is None:
            continue
        industry = r.get("industry") or r.get("icb_name") or ""
        news, sym_c, ind_c, mac_c = _decode_news(idx, sym, industry)
        rows.append({
            "symbol": sym, "industry": industry,
            "total": float(total), "decision": r.get("decision", "?"),
            "news": news, "sym_c": sym_c, "ind_c": ind_c, "mac_c": mac_c,
            "news_score_in_file": r.get("news_score"),
        })

    n_news = sum(1 for r in rows if r["news"] != 0)
    log.info(f"Mã có news_score ≠ 0 (decode fresh từ index): {n_news}/{len(rows)}")

    stale = sum(1 for r in rows
                if (r["news_score_in_file"] in (0, 0.0, None)) and r["news"] != 0)
    if stale:
        log.info(f"  Lưu ý: {stale} mã có news trong index nhưng news_score "
                 f"trong signals file = 0 → signals hiện tại là run TRƯỚC khi "
                 f"news bật; mô phỏng dưới dùng bản decode fresh (đúng mục đích what-if).")

    # ── Bảng chi tiết: chỉ mã có news ≠ 0, sort theo |news| ──
    log.info("─" * 96)
    log.info(f"{'MÃ':6s} {'news':>6s} (sym/ind/mac)      {'total':>7s} "
             f"{'S1':>7s} {'S2':>7s} {'S3':>7s}  decision: hiện tại → S1/S2/S3 nếu đổi")
    log.info("─" * 96)
    for r in sorted(rows, key=lambda x: abs(x["news"]), reverse=True):
        if r["news"] == 0:
            continue
        sims, flips = [], []
        for name, fn in SCENARIOS:
            nt = round(fn(r["total"], r["news"]), 2)
            nd = _decision(nt)
            sims.append(nt)
            flips.append(nd if nd != r["decision"] else "·")
        flip_str = ""
        if any(f != "·" for f in flips):
            flip_str = f"  {r['decision']} → " + "/".join(flips)
        log.info(f"{r['symbol']:6s} {r['news']:+6.2f} "
                 f"({r['sym_c']:+.1f}/{r['ind_c']:+.1f}/{r['mac_c']:+.1f})  "
                 f"{r['total']:7.2f} {sims[0]:7.2f} {sims[1]:7.2f} {sims[2]:7.2f}"
                 f"{flip_str}")

    # ── Summary từng kịch bản ──
    log.info("═" * 96)
    for name, fn in SCENARIOS:
        deltas, flip_list = [], []
        near_miss = []   # cách ngưỡng ≤ 3 điểm sau khi áp news
        for r in rows:
            nt = fn(r["total"], r["news"])
            deltas.append(nt - r["total"])
            nd = _decision(nt)
            if nd != r["decision"]:
                flip_list.append(f"{r['symbol']}({r['decision']}→{nd}, "
                                 f"news {r['news']:+.1f})")
            else:
                for cut in (THRESHOLD_STRONG_BUY, THRESHOLD_BUY,
                            THRESHOLD_NEUTRAL, THRESHOLD_SELL):
                    if abs(nt - cut) <= 3 and r["news"] != 0:
                        near_miss.append(r["symbol"])
                        break
        abs_d = [abs(d) for d in deltas if d != 0]
        log.info(f"[{name}] delta≠0: {len(abs_d)}/{len(rows)} mã | "
                 f"mean|Δ|={sum(abs_d)/len(abs_d):.2f} | "
                 f"max|Δ|={max(abs_d):.2f}" if abs_d else f"[{name}] không mã nào đổi điểm")
        if abs_d:
            log.info(f"  Decision flips: {len(flip_list)}"
                     + (f" → {', '.join(flip_list)}" if flip_list else ""))
            if near_miss:
                log.info(f"  Sát ngưỡng (≤3đ, chưa flip): {', '.join(sorted(set(near_miss)))}")
    log.info("═" * 96)
    log.info("READ-ONLY DONE — không file nào bị ghi/commit")
    return 0


if __name__ == "__main__":
    sys.exit(run())
