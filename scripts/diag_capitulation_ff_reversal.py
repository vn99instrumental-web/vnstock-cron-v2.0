"""
scripts/diag_capitulation_ff_reversal.py — Test giả thuyết "CAPITULATION + FF-REVERSAL"
=======================================================================================
XUẤT PHÁT (case PNJ, tháng 7-8/2026):
  - Mã rơi -51% bằng chuỗi giảm sàn; tín hiệu QUÁ BÁN (mean-reversion) bật CHÁY
    suốt cả đường rơi → vô dụng để bắt đáy (bằng chứng: bắt dao rơi).
  - Cái flip ĐÚNG lúc đáy mà KHÔNG lừa lúc rơi là KHỐI NGOẠI đảo chiều:
    ff_score đi -15 (bán ròng suốt) → -5 (dịu) → +10 (mua ròng) đúng lúc hồi bền.
GIẢ THUYẾT (pre-registered): sau một cú SẬP + có phiên capitulation, khi FOREIGN
  FLOW đảo từ bán ròng sang mua ròng → forward return DƯƠNG (excess, sau cost),
  và tín hiệu này THÊM giá trị so với "chỉ giảm sâu" và so với "giảm sâu + quá bán".

ISOLATION / KỶ LUẬT (giống các diag khác):
  ✗ KHÔNG import utils/ steps/ config  ✗ KHÔNG ghi bất kỳ file nào (read-only thuần)
  ✓ Chỉ đọc: output/history/v2f_outcomes/*.jsonl   (ret_5d/10d + t0_close matured)
             output/history/v2f_predictions/*.jsonl (ff_score, price)
             output/history/v2f_predictions_v3/*.jsonl (trade_mean_reversion_norm, breakout_norm)
  ✓ Join theo (symbol, signal_date) sau khi dedup daily_last (snap muộn nhất/ngày)

METRIC: excess ret_5d = ret_5d(mã) - mean ret_5d(universe cùng NGÀY). Verdict so
  chi phí vòng 0.30-0.50% (mid 0.40%). Kèm time-split hold-out (nửa ngày đầu vs sau).

CẢNH BÁO CÔNG SUẤT: dữ liệu forward hiện chỉ ~2 tháng, phần lớn là 1 regime
  (sập T7 + hồi đầu T8). Pattern capitulation hiếm → n có thể rất nhỏ. Mọi kết
  luận gắn INDICATIVE nếu n_signals < MIN_N hoặc n_days < MIN_DAYS. Ngưỡng dưới
  được đặt a-priori từ CƠ CHẾ case PNJ (không tuning theo kết quả); việc suy ngưỡng
  từ 1 mã là bias in-sample nhẹ → chính vì thế mới cần cross-section + hold-out này.

TRIGGER: workflow_dispatch debug.yml → script = scripts/diag_capitulation_ff_reversal.py
"""
import os
import sys
import json
import glob
import logging
import statistics as st
from pathlib import Path
from collections import defaultdict

# ── Isolation guard: không cho production modules lọt vào ──────────────
for _mod in list(sys.modules.keys()):
    if _mod.startswith(("utils.", "steps.")) or _mod == "config":
        raise RuntimeError(f"ISOLATION VIOLATION: {_mod} đã được import")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cap_ff_rev")

REPO_ROOT   = Path(__file__).resolve().parent.parent
HISTORY     = REPO_ROOT / "output" / "history"
OUT_DIR     = HISTORY / "v2f_outcomes"
PRED23_DIR  = HISTORY / "v2f_predictions"
PRED3_DIR   = HISTORY / "v2f_predictions_v3"

# ══════════════════════════════════════════════════════════════════════
# THAM SỐ ĐĂNG KÝ TRƯỚC — KHÔNG sửa sau khi đã nhìn thấy kết quả
# ══════════════════════════════════════════════════════════════════════
HORIZON_PRIMARY = 5        # khung trade
HORIZON_REF     = 10       # tham chiếu (chỉ report)

# Deep-drop (bối cảnh sập): drawdown đỉnh→hiện tại trong cửa sổ gần
DD_WINDOW       = 20       # phiên nhìn lại tìm đỉnh
DD_MIN_PCT      = 25.0     # % sụt tối thiểu tính từ đỉnh cửa sổ

# Capitulation: có phiên giảm gần sàn trong cửa sổ gần
CAP_WINDOW      = 10       # phiên nhìn lại
CAP_FLOOR_RET   = -6.0     # % — 1 phiên <= ngưỡng này coi là 'giảm sàn'
CAP_MIN_DAYS    = 1        # tối thiểu số phiên sàn trong cửa sổ

# FF-reversal: khối ngoại đảo từ bán ròng sang mua ròng
FF_LOOK         = 5        # phiên nhìn lại tìm 'từng bán ròng'
FF_NEG_THR      = -5.0     # min ff_score trong cửa sổ <= ngưỡng này = 'từng bán ròng'
FF_POS_THR      = 3.0      # ff_score hôm nay >= ngưỡng này = 'đang mua ròng'

# Kinh tế học
COST_RT_LOW     = 0.30
COST_RT_HIGH    = 0.50
COST_RT_MID     = 0.40

# Guard công suất
MIN_N           = 20       # < → verdict INDICATIVE
MIN_DAYS        = 30

CORP_ACTION     = {"OCB", "CTR", "PVD", "VCG", "VTP", "DPM"}  # loại khỏi phân tích


# ══════════════════════════════════════════════════════════════════════
# IO — đọc ledger (read-only)
# ══════════════════════════════════════════════════════════════════════
def _read_jsonl(dirpath: Path) -> list:
    recs = []
    for fp in sorted(glob.glob(str(dirpath / "*.jsonl"))):
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return recs


def _daily_last(recs: list, keep_keys: list) -> dict:
    """1 obs / (symbol, signal_date): giữ snap_time MUỘN NHẤT."""
    best = {}
    for r in recs:
        sym = r.get("symbol"); sd = r.get("signal_date")
        if not sym or not sd:
            continue
        key = (sym, sd)
        snap = r.get("snap_time", "") or ""
        if key not in best or snap >= best[key][0]:
            best[key] = (snap, {k: r.get(k) for k in keep_keys})
    return {k: v[1] for k, v in best.items()}


# ══════════════════════════════════════════════════════════════════════
# CƠ CHẾ TÍN HIỆU
# ══════════════════════════════════════════════════════════════════════
def build_series(closes_by_sym: dict, ff_by_sym: dict):
    """Trả per-symbol: list[(date, close, daily_ret_pct, ff_score)] sắp theo ngày."""
    series = {}
    for sym, cmap in closes_by_sym.items():
        dates = sorted(cmap)
        seq = []
        prev = None
        for d in dates:
            c = cmap[d]
            if c is None:
                continue
            ret = (c / prev - 1) * 100 if prev else None
            seq.append([d, c, ret, ff_by_sym.get(sym, {}).get(d)])
            prev = c
        series[sym] = seq
    return series


def eval_signal(seq: list, i: int) -> dict:
    """Đánh giá 3 điều kiện tại vị trí i trong chuỗi 1 mã. Trả cờ bool."""
    date, close, _, ff = seq[i]
    # deep drop: đỉnh trong DD_WINDOW phiên trước (gồm hiện tại)
    lo = max(0, i - DD_WINDOW + 1)
    win = seq[lo:i + 1]
    peak = max(x[1] for x in win)
    dd = (close / peak - 1) * 100 if peak else 0.0
    deep = dd <= -DD_MIN_PCT

    # capitulation: số phiên giảm sàn trong CAP_WINDOW gần
    loc = max(0, i - CAP_WINDOW + 1)
    floor_days = sum(1 for x in seq[loc:i + 1]
                     if x[2] is not None and x[2] <= CAP_FLOOR_RET)
    capdone = floor_days >= CAP_MIN_DAYS

    # FF reversal: từng bán ròng (min ff trong FF_LOOK <= NEG) & nay mua ròng (>= POS)
    lof = max(0, i - FF_LOOK)
    ff_hist = [x[3] for x in seq[lof:i + 1] if x[3] is not None]
    ff_flip = False
    if ff is not None and ff_hist:
        ff_flip = (min(ff_hist) <= FF_NEG_THR) and (ff >= FF_POS_THR)

    return {"dd": dd, "deep": deep, "cap": capdone,
            "ff_flip": ff_flip, "floor_days": floor_days}


# ══════════════════════════════════════════════════════════════════════
# THỐNG KÊ COHORT
# ══════════════════════════════════════════════════════════════════════
def _verdict(mean_excess: float, n: int, n_days: int) -> str:
    if n < MIN_N or n_days < MIN_DAYS:
        return f"INDICATIVE (n={n}, days={n_days} < guard)"
    gap = mean_excess
    if abs(gap) <= COST_RT_HIGH:
        return f"NO EDGE (excess {gap:+.3f}% <= chi phí {COST_RT_LOW}-{COST_RT_HIGH}%)"
    net = abs(gap) - COST_RT_MID
    side = "DƯƠNG" if gap > 0 else "ÂM"
    return f"EDGE {side} net~{net:+.3f}% sau cost (excess {gap:+.3f}%)"


def summarize(name: str, rows: list):
    if not rows:
        log.info(f"{name:44} (0 obs)")
        return
    n = len(rows)
    syms = len({r["sym"] for r in rows})
    ndays = len({r["date"] for r in rows})
    m5   = st.mean([r["ret5"] for r in rows])
    ex5  = st.mean([r["ex5"] for r in rows])
    med  = st.median([r["ex5"] for r in rows])
    p_ex0   = sum(1 for r in rows if r["ex5"] > 0) / n
    p_excst = sum(1 for r in rows if r["ex5"] > COST_RT_MID) / n
    log.info(f"{name:44} n={n:4} sym={syms:3} d={ndays:3} | ret5={m5:+.2f}% "
             f"excess={ex5:+.2f}% med={med:+.2f}% | P(ex>0)={p_ex0:.0%} "
             f"P(ex>{COST_RT_MID})={p_excst:.0%} | {_verdict(ex5, n, ndays)}")


def holdout_split(name: str, rows: list):
    if len(rows) < 2 * MIN_N:
        log.info(f"  [hold-out] {name}: n={len(rows)} quá nhỏ để split có ý nghĩa.")
        return
    dates = sorted({r["date"] for r in rows})
    cut = dates[len(dates) // 2]
    ins = [r for r in rows if r["date"] < cut]
    out = [r for r in rows if r["date"] >= cut]
    ex_in  = st.mean([r["ex5"] for r in ins]) if ins else float("nan")
    ex_out = st.mean([r["ex5"] for r in out]) if out else float("nan")
    log.info(f"  [hold-out] cut={cut} | in-sample excess={ex_in:+.2f}% (n={len(ins)}) "
             f"→ hold-out excess={ex_out:+.2f}% (n={len(out)})")


# ══════════════════════════════════════════════════════════════════════
def run():
    log.info("=== DIAG capitulation + FF-reversal (read-only) ===")
    log.info(f"Pre-reg: DD>={DD_MIN_PCT}%/{DD_WINDOW}p | floor<={CAP_FLOOR_RET}% x>={CAP_MIN_DAYS}"
             f"/{CAP_WINDOW}p | FF flip min<={FF_NEG_THR}→now>={FF_POS_THR}/{FF_LOOK}p"
             f" | cost {COST_RT_LOW}-{COST_RT_HIGH}%")

    outs = _read_jsonl(OUT_DIR)
    if not outs:
        log.warning(f"Không có outcomes tại {OUT_DIR} — DỪNG."); return
    pred23 = _read_jsonl(PRED23_DIR)
    pred3  = _read_jsonl(PRED3_DIR)

    # outcomes trade lens, daily_last theo (sym, signal_date)
    o_last = _daily_last([r for r in outs if r.get("lens") == "trade"],
                         ["t0_close", "ret_5d", "ret_10d", "n_bars"])
    p23_last = _daily_last(pred23, ["ff_score", "price"])
    p3_last  = _daily_last(pred3,  ["trade_mean_reversion_norm", "trade_breakout_norm"])

    # chuỗi close + ff theo mã (close ưu tiên t0_close, fill bằng price predictions)
    closes_by_sym = defaultdict(dict)
    ff_by_sym     = defaultdict(dict)
    for (sym, sd), o in o_last.items():
        if sym in CORP_ACTION:
            continue
        c = o.get("t0_close")
        if c is None:
            c = (p23_last.get((sym, sd)) or {}).get("price")
        if c is not None:
            closes_by_sym[sym][sd] = c
    # bổ sung ngày chỉ có predictions (chưa mature outcome) để chuỗi liền cho lookback
    for (sym, sd), p in p23_last.items():
        if sym in CORP_ACTION:
            continue
        if sd not in closes_by_sym[sym] and p.get("price") is not None:
            closes_by_sym[sym][sd] = p["price"]
        if p.get("ff_score") is not None:
            ff_by_sym[sym][sd] = p["ff_score"]

    series = build_series(closes_by_sym, ff_by_sym)
    idx = {sym: {row[0]: k for k, row in enumerate(seq)} for sym, seq in series.items()}

    # gom obs CÓ forward ret_5d matured
    obs = []
    for (sym, sd), o in o_last.items():
        if sym in CORP_ACTION:
            continue
        r5 = o.get("ret_5d")
        if r5 is None or (o.get("n_bars") or 0) < HORIZON_PRIMARY:
            continue
        i = idx.get(sym, {}).get(sd)
        if i is None:
            continue
        sig = eval_signal(series[sym], i)
        mr = (p3_last.get((sym, sd)) or {}).get("trade_mean_reversion_norm")
        r10 = o.get("ret_10d") if (o.get("n_bars") or 0) >= HORIZON_REF else None
        obs.append({"sym": sym, "date": sd, "ret5": r5, "ret10": r10,
                    "mr": mr, **sig})

    if not obs:
        log.warning("Không obs nào có forward ret_5d matured — DỪNG."); return

    # excess vs mean universe cùng ngày
    day_mean = defaultdict(list)
    for x in obs:
        day_mean[x["date"]].append(x["ret5"])
    day_mean = {d: st.mean(v) for d, v in day_mean.items()}
    for x in obs:
        x["ex5"] = x["ret5"] - day_mean[x["date"]]

    log.info(f"Universe obs (daily_last, loại corp-action, có ret_5d): {len(obs)} "
             f"| mã={len({x['sym'] for x in obs})} | ngày={len(day_mean)}")
    log.info("-" * 118)

    # ── COHORTS ──
    universe = obs
    deep      = [x for x in obs if x["deep"] and x["cap"]]
    deep_mr   = [x for x in deep if (x["mr"] or 0) > 0]                 # naive (đã biết fail)
    deep_ff   = [x for x in deep if x["ff_flip"]]                       # GIẢ THUYẾT
    deep_ff_only = [x for x in obs if x["deep"] and x["ff_flip"]]       # bỏ điều kiện cap
    ff_flip_all  = [x for x in obs if x["ff_flip"]]                     # FF-flip toàn universe (đối chứng)

    summarize("UNIVERSE (baseline)", universe)
    summarize("Deep-drop + capitulation", deep)
    summarize("  + QUÁ BÁN (mr>0)  [naive control]", deep_mr)
    summarize("  + FF-REVERSAL     [HYPOTHESIS]", deep_ff)
    summarize("Deep-drop + FF-reversal (bỏ cap)", deep_ff_only)
    summarize("FF-reversal (toàn universe, đối chứng)", ff_flip_all)

    log.info("-" * 118)
    holdout_split("Deep+cap+FF-reversal", deep_ff)
    holdout_split("Deep+cap", deep)

    # đếm mã distinct thắng sau cost trong nhóm giả thuyết
    if deep_ff:
        by = defaultdict(list)
        for x in deep_ff:
            by[x["sym"]].append(x["ex5"])
        win = [s for s, v in by.items() if st.mean(v) > COST_RT_MID]
        log.info(f"[HYPOTHESIS] {len(by)} mã distinct; excess-after-cost DƯƠNG: "
                 f"{len(win)}/{len(by)} → {sorted(win)}")

    log.info("=== DONE (read-only, không ghi file) ===")


if __name__ == "__main__":
    run()
