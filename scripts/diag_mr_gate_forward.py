"""
scripts/diag_mr_gate_forward.py — KIỂM ĐỊNH GATE mean_reversion BẰNG FORWARD LEDGER
====================================================================================
MỤC ĐÍCH: Bảng GATE hiện tại đặt mean_reversion = 0.0 ở MỌI regime (GATE v4,
13/08). Căn cứ gốc là BACKTEST parquet (diag_mr_regime_v2f) — mà theo kỷ luật
23/07 backtest đã CẠN, forward THẮNG. Script này đo lại quyết định đó bằng
FORWARD LEDGER thật (ledger V4 có trade_mean_reversion_norm + regime tại thời
điểm chấm), KHÔNG đụng backtest, KHÔNG sửa production.

ĐO (Spearman IC của giá trị engine ĐÃ cộng vào điểm, vs return_5d thực tế):
  - Factor gộp : trade_mean_reversion_norm
  - Từng tín hiệu con: s_willr_mr, s_bb_mr, s_overext_ema, s_rs_reversal
  Tách theo regime (UPTREND/SIDEWAYS/DOWNTREND/DEEP_DOWN) + ô __ALL__.

NGUỒN FORWARD (ưu tiên, read-only):
  1. history/v2f_predictions_v4  JOIN  history/v2f_outcomes_v4  theo pred_id
     (đây là sổ ĐÚNG khi evaluator đã chín outcomes cho V4).
  2. Fallback: nếu chưa có outcomes_v4 → thử nối chéo (symbol,signal_date,
     snap_time) sang mọi *_outcomes*/ret_5d để tận dụng return đã chín.
  Daily-last: mỗi (symbol, signal_date) lấy snap_time MUỘN nhất (khớp logic sổ).

TIÊU CHÍ ĐĂNG KÝ TRƯỚC (hard-code — KHÔNG sửa sau khi thấy số):
  MIN_DAYS   = 30   # < 30 phiên riêng biệt trong ô → "THƯA — KHÔNG TIN"
  MIN_N      = 20   # < 20 mẫu trong ô → "THƯA — KHÔNG TIN"
  T_ALIVE    = 2.0
  Nhãn ô đủ dày:  ALIVE  nếu IC>0 & |t|>=2.0
                  DEAD   nếu IC<0 & |t|>=2.0
                  WEAK   còn lại (không kết luận)
  KHUYẾN NGHỊ GATE (chỉ in, KHÔNG áp):
    * Giữ 0.0 ở regime nào MR = DEAD (đủ dày).
    * Bật lại (đề xuất 0.5 nửa liều) ở regime nào MR = ALIVE (đủ dày).
    * Regime THƯA → GIỮ NGUYÊN gate hiện tại (không đủ căn cứ để đổi).

ISOLATION: KHÔNG import utils/steps/config. Chỉ đọc output/history/*, chỉ in log.
TRIGGER : debug.yml → script = scripts/diag_mr_gate_forward.py
CHANGELOG: v1 (2026-08-14) — initial.
"""
import sys, json, glob, math, logging
from collections import defaultdict, Counter

for _m in list(sys.modules):
    if _m.startswith(("utils.", "steps.")) or _m == "config":
        raise RuntimeError(f"ISOLATION VIOLATION: {_m} imported")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("diag_mr_gate_fwd")

MIN_DAYS, MIN_N, T_ALIVE = 30, 20, 2.0
PRED_V4 = "output/history/v2f_predictions_v4/*.jsonl"
OUT_V4  = "output/history/v2f_outcomes_v4/*.jsonl"
OUT_ANY = "output/history/v2f_outcomes*/*.jsonl"      # fallback nguồn ret_5d
MR_FACTOR = "trade_mean_reversion_norm"
MR_SIGNALS = ["s_willr_mr", "s_bb_mr", "s_overext_ema", "s_rs_reversal"]
REGIMES = ["UPTREND", "SIDEWAYS", "DOWNTREND", "DEEP_DOWN"]


def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _load(pat):
    rows = []
    for f in sorted(glob.glob(pat)):
        with open(f) as fh:
            for ln in fh:
                ln = ln.strip()
                if ln:
                    rows.append(json.loads(ln))
    return rows


def _spearman(xs, ys):
    n = len(xs)
    if n < 3:
        return None, None, n
    def rank(a):
        order = sorted(range(n), key=lambda i: a[i]); rk = [0.0]*n; i = 0
        while i < n:
            j = i
            while j+1 < n and a[order[j+1]] == a[order[i]]:
                j += 1
            avg = (i+j)/2 + 1
            for t in range(i, j+1):
                rk[order[t]] = avg
            i = j+1
        return rk
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    cov = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    vx = sum((rx[i]-mx)**2 for i in range(n)); vy = sum((ry[i]-my)**2 for i in range(n))
    if vx == 0 or vy == 0:
        return None, None, n
    rho = cov/math.sqrt(vx*vy)
    t = rho*math.sqrt((n-2)/max(1e-12, 1-rho**2)) if abs(rho) < 1 else float("inf")
    return rho, t, n


def _verdict(rho, t, n, ndays):
    if n < MIN_N or ndays < MIN_DAYS:
        return "THƯA—KHÔNG TIN"
    if rho is None:
        return "n/a"
    if abs(t) >= T_ALIVE:
        return "ALIVE" if rho > 0 else "DEAD"
    return "WEAK"


def run():
    preds = _load(PRED_V4)
    log.info("=== DIAG MR GATE (FORWARD) ===")
    if not preds:
        log.info("Không có ledger V4 (%s). Dừng.", PRED_V4); return
    log.info("V4 predictions: %d dòng | signal_date %s..%s",
             len(preds),
             min(p.get("signal_date","") for p in preds),
             max(p.get("signal_date","") for p in preds))

    # ── nguồn return_5d ─────────────────────────────────────────────
    ret_by_pid, ret_by_key = {}, {}
    outs_v4 = _load(OUT_V4)
    if outs_v4:
        src = "v2f_outcomes_v4 (JOIN pred_id) — ĐÚNG SỔ"
        for o in outs_v4:
            r = _num(o.get("ret_5d"))
            if r is not None and o.get("pred_id"):
                ret_by_pid[o["pred_id"]] = r
    else:
        src = "FALLBACK nối chéo (symbol,signal_date,snap_time) sang *_outcomes*"
        for o in _load(OUT_ANY):
            r = _num(o.get("ret_5d"))
            if r is None:
                continue
            k = (o.get("symbol"), o.get("signal_date"), o.get("snap_time"))
            ret_by_key[k] = r
    log.info("Nguồn return_5d: %s | pid=%d key=%d", src, len(ret_by_pid), len(ret_by_key))

    # ── daily-last theo (symbol, signal_date) ───────────────────────
    best = {}   # (sym,date) -> (snap_time, pred)
    for p in preds:
        k = (p.get("symbol"), p.get("signal_date"))
        st = p.get("snap_time", "")
        if k not in best or st > best[k][0]:
            best[k] = (st, p)

    joined = []   # (regime, pred, ret5d)
    for (sym, date), (st, p) in best.items():
        r = None
        if ret_by_pid:
            r = ret_by_pid.get(p.get("pred_id"))
        if r is None and ret_by_key:
            r = ret_by_key.get((sym, date, st))
        if r is None:
            r = _num(p.get("result_5d")) or _num(p.get("return_5d"))
        if r is not None:
            joined.append((p.get("regime"), p, r))

    log.info("Mẫu (symbol,date) daily-last: %d | ĐÃ CHÍN có return_5d: %d",
             len(best), len(joined))
    if not joined:
        log.info("")
        log.info(">>> CHƯA CÓ OUTCOME NÀO CHÍN cho ledger V4 → KHÔNG THỂ forward-"
                 "validate gate MR lúc này.")
        log.info(">>> KHUYẾN NGHỊ: GIỮ NGUYÊN gate hiện tại. Chạy lại script này khi "
                 "outcomes_v4 bắt đầu chín (≥ MIN_N=20 & ≥ MIN_DAYS=30 phiên/ô).")
        return

    # ── IC theo regime cho factor gộp + từng tín hiệu con ───────────
    def report(field):
        log.info("")
        log.info("── %s ──", field)
        log.info("%-12s %5s %5s %8s %7s   %s", "regime", "N", "days", "IC", "t", "verdict")
        buckets = defaultdict(list)  # regime -> [(x, ret, date)]
        for reg, p, r in joined:
            x = _num(p.get(field))
            if x is not None:
                buckets[reg].append((x, r, p.get("signal_date")))
        allv = []
        for reg in REGIMES + ["__ALL__"]:
            v = ([xy for k in REGIMES for xy in buckets.get(k, [])]
                 if reg == "__ALL__" else buckets.get(reg, []))
            if not v:
                log.info("%-12s %5d   —      —      —    (không có mẫu)", reg, 0); continue
            xs = [a for a, _, _ in v]; ys = [b for _, b, _ in v]
            ndays = len(set(d for _, _, d in v))
            rho, t, n = _spearman(xs, ys)
            vd = _verdict(rho, t, n, ndays)
            log.info("%-12s %5d %5d %8s %7s   %s", reg, n, ndays,
                     f"{rho:+.3f}" if rho is not None else "n/a",
                     f"{t:+.2f}" if t is not None else "n/a", vd)

    report(MR_FACTOR)
    for s in MR_SIGNALS:
        report(s)

    # ── khuyến nghị gate (CHỈ IN) ───────────────────────────────────
    log.info("")
    log.info("── KHUYẾN NGHỊ GATE mean_reversion (pre-registered, CHỈ IN) ──")
    buckets = defaultdict(list)
    for reg, p, r in joined:
        x = _num(p.get(MR_FACTOR))
        if x is not None:
            buckets[reg].append((x, r, p.get("signal_date")))
    for reg in REGIMES:
        v = buckets.get(reg, [])
        if not v:
            log.info("  %-10s : không mẫu → GIỮ 0.0", reg); continue
        rho, t, n = _spearman([a for a,_,_ in v], [b for _,b,_ in v])
        nd = len(set(d for _,_,d in v)); vd = _verdict(rho, t, n, nd)
        if vd == "ALIVE":
            rec = "ĐỀ XUẤT BẬT 0.5 (nửa liều) — có edge forward"
        elif vd == "DEAD":
            rec = "GIỮ 0.0 — xác nhận forward DEAD"
        else:
            rec = "GIỮ 0.0 — chưa đủ căn cứ đổi (THƯA/WEAK)"
        log.info("  %-10s : %-14s → %s", reg, vd, rec)
    log.info("")
    log.info("LƯU Ý: đây là read-only. Đổi GATE phải: (1) bump GATE_VERSION → reset "
             "bucket forward v4; (2) chỉ 1 thay đổi/chu kỳ; (3) đăng ký trước.")


if __name__ == "__main__":
    run()
