"""
scripts/diag_hold_calibration.py — Calibrate ngưỡng khung HOLD (READ-ONLY)
==========================================================================
Chạy qua debug.yml (workflow_dispatch). KHÔNG ghi file, KHÔNG sửa scoring,
KHÔNG import module production (isolation guard). Stdlib only.

MỤC ĐÍCH
--------
Trả lời bằng SỐ THẬT (không đoán) 2 câu:
  1) BUY SIGNAL: cắt top bao nhiêu % `score_hold` thì excess-return vượt
     chi phí vòng lệnh? (đề xuất pre-register: TOP decile)
  2) QUALITY TAG: `rank_fund_grp` (percentile cơ bản TRONG NGÀNH) ở mức nào
     thì đáng gắn ⭐QUALITY_HOLD? — tránh bẫy bias ngân hàng của QUALITY_BUY cũ.

VÌ SAO PHẢI JOIN
----------------
Outcome record CHỈ mang return (ret_5d/10d/20d), KHÔNG mang score_hold /
rank_fund_grp. Ngược lại predictions ledger mang score_hold + rank_fund_grp
nhưng KHÔNG mang return (field result_* = "PENDING", không backfill).
→ Phải JOIN: predictions (điểm) × outcomes (return) theo (symbol, signal_date).

Return của 1 (mã, ngày) là BẤT BIẾN theo scoring version (chỉ phụ thuộc giá +
horizon) → có thể mượn return đã tính của MỌI sổ (kể cả v2.3) để chấm điểm v3.
Ưu tiên sổ native của chính track; nếu chưa có thì mượn — kết quả giống hệt.

ĐỘ CHÍN DỮ LIỆU (tự in, không giả định)
---------------------------------------
  - score_hold có từ 06/07 → ret_10d chín cho signal ≤ ~18/07 (proxy tốt NGAY).
  - ret_20d (khung hold thật ~1 tháng) chín dần tới giữa/cuối tháng 8.
  - rank_fund_grp mới shadow-write từ 22/07 → return chưa chín cái nào tới đầu 8.
Script tự report "chờ data" cho slice nào n=0, KHÔNG bịa verdict.

KỶ LUẬT (pre-registration)
--------------------------
Ngưỡng khoá cứng bên dưới (BUY_PCT / AVOID_PCT / QUALITY_CUT). Diag chỉ ĐO
excess-vs-cost tại ngưỡng đã khoá — KHÔNG grid-search tìm ngưỡng tốt nhất
(đó là mining → false discovery). Muốn đổi ngưỡng → sửa hằng số + ghi lý do.

TRIGGER
-------
    workflow_dispatch → input script = scripts/diag_hold_calibration.py
ENV (tuỳ chọn):
    HOLD_CAL_TRACK   : predictions track ("v3" mặc định | "v4" | "v23")
    HOLD_CAL_OUTPUT  : thư mục output (mặc định "output")

CHANGELOG
  v1 (2026-08-02) — initial. Join predictions×outcomes, excess theo decile +
                    tail cut, economics vs cost. Report chờ-data cho ret_20d &
                    rank_fund_grp. Sẵn dùng sổ *_hold10 native khi có.
"""
import os
import sys
import json
import glob
import statistics as st
from collections import defaultdict

# ── Isolation guard: cấm module production lọt vào ────────────────────
for _mod in list(sys.modules.keys()):
    if _mod.startswith(("utils.", "steps.")) or _mod == "config":
        raise RuntimeError(f"ISOLATION VIOLATION: {_mod} đã import")

# ══════════════════════════════════════════════════════════════════════
# PRE-REGISTERED THRESHOLDS — khoá cứng, KHÔNG grid-search
# ══════════════════════════════════════════════════════════════════════
BUY_PCT     = 0.90    # score_hold rank_pct ≥ 0.90 (top decile) → HOLD_BUY
AVOID_PCT   = 0.20    # rank_pct ≤ 0.20 (bottom 2 decile)       → AVOID
QUALITY_CUT = 0.70    # rank_fund_grp ≥ 0.70 (~top tercile ngành) → ⭐QUALITY_HOLD
COST_RT     = 0.50    # chi phí vòng lệnh (cận trên 0.30–0.50%) — mốc economics
MIN_OBS     = 50      # dưới ngưỡng này → không đủ để kết luận, chỉ báo "thiếu"

OUTPUT_DIR = os.getenv("HOLD_CAL_OUTPUT", "output")
TRACK      = os.getenv("HOLD_CAL_TRACK", "v3").lower()

# Map track → (predictions subdir, list sổ outcome native của track)
_SUFFIX = {"v3": "_v3", "v4": "_v4", "v23": ""}[TRACK]
PRED_DIR = f"history/v2f_predictions{_SUFFIX}"
# Sổ outcome native của track (nếu đã có sẽ join theo pred_id — sạch nhất)
NATIVE_OUT = [
    f"history/v2f_outcomes{_SUFFIX}_hold10",   # ret_5d, ret_10d (A: sub-horizon)
    f"history/v2f_outcomes{_SUFFIX}_hold",      # ret_10d, ret_20d
    f"history/v2f_outcomes{_SUFFIX}",           # trade: ret_5d, ret_10d
]
# Sổ mượn return (mọi track — return bất biến theo version). v2.3 phủ rộng nhất.
BORROW_OUT = [
    "history/v2f_outcomes",        # v2.3 trade: ret_5d, ret_10d
    "history/v2f_outcomes_hold",   # v2.3 hold:  ret_10d, ret_20d
    "history/v2f_outcomes_hold10", # v2.3 hold10 (nếu có): ret_5d, ret_10d
]


# ══════════════════════════════════════════════════════════════════════
# IO — stdlib JSONL
# ══════════════════════════════════════════════════════════════════════

def _load_jsonl_dir(subdir):
    """Đọc mọi *.jsonl trong OUTPUT_DIR/subdir/. Trả list dict."""
    out = []
    for f in sorted(glob.glob(os.path.join(OUTPUT_DIR, subdir, "*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def _is_num(v):
    return isinstance(v, (int, float)) and not (isinstance(v, float) and v != v)


# ══════════════════════════════════════════════════════════════════════
# BUILD return map: (symbol, signal_date) → {ret_5d, ret_10d, ret_20d}
# ══════════════════════════════════════════════════════════════════════

def build_return_map():
    ret = defaultdict(dict)
    n_src = defaultdict(int)
    for sub in NATIVE_OUT + BORROW_OUT:
        recs = _load_jsonl_dir(sub)
        if recs:
            n_src[sub] = len(recs)
        for r in recs:
            sym, d = r.get("symbol"), r.get("signal_date")
            if not sym or not d:
                continue
            k = (sym, d)
            for h in ("ret_5d", "ret_10d", "ret_20d"):
                if _is_num(r.get(h)):
                    ret[k].setdefault(h, r[h])   # setdefault: giữ nguồn đầu tiên
    return ret, n_src


# ══════════════════════════════════════════════════════════════════════
# LOAD predictions (daily-last: 1 record/mã/ngày, snap muộn nhất)
# ══════════════════════════════════════════════════════════════════════

def load_predictions():
    recs = _load_jsonl_dir(PRED_DIR)
    best = {}
    for r in recs:
        if not _is_num(r.get("score_hold")):
            continue
        sym, d = r.get("symbol"), r.get("signal_date")
        if not sym or not d:
            continue
        k = (sym, d)
        cur = best.get(k)
        if cur is None or (r.get("snap_time") or "") > (cur.get("snap_time") or ""):
            best[k] = r
    return list(best.values())


# ══════════════════════════════════════════════════════════════════════
# ANALYSIS
# ══════════════════════════════════════════════════════════════════════

def _excess(hits, ret_key):
    """hits = list[(pred, ret_map)] → list[(score_hold, excess, raw, rfg)].
    excess = ret - trung bình cùng ngày (loại beta thị trường)."""
    rows = []
    byday = defaultdict(list)
    tmp = []
    for pred, rmap in hits:
        v = rmap.get(ret_key)
        if not _is_num(v):
            continue
        tmp.append((pred, v))
        byday[pred["signal_date"]].append(v)
    dm = {d: st.mean(vs) for d, vs in byday.items()}
    for pred, v in tmp:
        rfg = pred.get("rank_fund_grp")
        rows.append((pred["score_hold"], v - dm[pred["signal_date"]], v,
                     rfg if _is_num(rfg) else None))
    return rows


def _corr(xs, ys):
    if len(xs) < 3:
        return float("nan")
    mx, my = st.mean(xs), st.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs)
    sx, sy = st.pstdev(xs), st.pstdev(ys)
    return cov / (sx * sy) if sx and sy else float("nan")


def report_buy_signal(rows, ret_key):
    print(f"\n{'='*66}\n  BUY SIGNAL — score_hold × {ret_key}\n{'='*66}")
    if len(rows) < MIN_OBS:
        print(f"  n={len(rows)} < {MIN_OBS} → CHƯA ĐỦ DATA. "
              f"({ret_key} chín dần theo thời gian — chạy lại sau.)")
        return
    rows = sorted(rows)
    n = len(rows)
    print(f"  n={n}  corr(score_hold,{ret_key})="
          f"{_corr([r[0] for r in rows], [r[2] for r in rows]):+.4f}")
    print(f"\n  {'decile':>6} {'sh_range':>15} {'nn':>4} {'excess':>8} {'raw':>8}")
    for i in range(10):
        a, b = i * n // 10, (i + 1) * n // 10
        c = rows[a:b]
        if not c:
            continue
        print(f"  {i+1:>6} {f'{c[0][0]:+.1f}..{c[-1][0]:+.1f}':>15} {len(c):>4} "
              f"{st.mean(x[1] for x in c):>+7.2f}% {st.mean(x[2] for x in c):>+7.2f}%")

    # Economics tại ngưỡng đã pre-register
    buy = rows[int(BUY_PCT * n):]
    avoid = rows[:int(AVOID_PCT * n)]
    print(f"\n  ── Economics tại ngưỡng khoá (cost vòng lệnh = {COST_RT:.2f}%) ──")
    for name, c in (("HOLD_BUY (top %d%%)" % round((1 - BUY_PCT) * 100), buy),
                    ("AVOID (bot %d%%)" % round(AVOID_PCT * 100), avoid)):
        if not c:
            continue
        ex = st.mean(x[1] for x in c)
        wr = sum(1 for x in c if x[2] > 0) / len(c)
        print(f"    {name:<22} n={len(c):>3}  excess={ex:+.2f}%  winrate>0={wr:.0%}")
    ex_buy = st.mean(x[1] for x in buy) if buy else 0
    verdict = ("VƯỢT cost ✓" if ex_buy > COST_RT
               else "chưa vượt cost ✗" if ex_buy > 0
               else "ÂM ✗✗")
    print(f"\n  → VERDICT BUY (excess top decile vs cost {COST_RT:.2f}%): "
          f"{ex_buy:+.2f}%  {verdict}")
    print(f"    (Lưu ý: in-sample nếu chỉ 1 regime; OOS thật = signal tháng sau.)")


def report_quality(rows, ret_key):
    print(f"\n{'='*66}\n  QUALITY TAG — rank_fund_grp × {ret_key}\n{'='*66}")
    q = [(rfg, ex, raw) for (_sh, ex, raw, rfg) in rows if rfg is not None]
    if len(q) < MIN_OBS:
        print(f"  n={len(q)} < {MIN_OBS} → CHƯA ĐỦ DATA.")
        print(f"  rank_fund_grp mới shadow-write từ 22/07; return chín sớm nhất")
        print(f"  ~đầu/giữa tháng 8. Đây là giả thuyết sống duy nhất — chờ đúng data.")
        return
    q.sort()
    n = len(q)
    print(f"  n={n}  corr(rank_fund_grp,{ret_key})="
          f"{_corr([x[0] for x in q], [x[2] for x in q]):+.4f}")
    print(f"\n  {'tercile':>8} {'rfg_range':>15} {'nn':>4} {'excess':>8}")
    for i, lbl in enumerate(("THẤP", "GIỮA", "CAO")):
        a, b = i * n // 3, (i + 1) * n // 3
        c = q[a:b]
        if not c:
            continue
        print(f"  {lbl:>8} {f'{c[0][0]:.2f}..{c[-1][0]:.2f}':>15} {len(c):>4} "
              f"{st.mean(x[1] for x in c):>+7.2f}%")
    qual = [x for x in q if x[0] >= QUALITY_CUT]
    if qual:
        ex = st.mean(x[1] for x in qual)
        v = ("VƯỢT cost ✓" if ex > COST_RT else "chưa vượt ✗" if ex > 0 else "ÂM ✗✗")
        print(f"\n  → ⭐QUALITY_HOLD (rank_fund_grp≥{QUALITY_CUT}): n={len(qual)} "
              f"excess={ex:+.2f}%  {v}")


def report_combined(rows, ret_key):
    """Ô giao: top-decile score_hold ∩ QUALITY_HOLD — conviction thật."""
    has_rfg = [r for r in rows if r[3] is not None]
    if len(has_rfg) < MIN_OBS:
        return
    rows_s = sorted(rows)
    n = len(rows_s)
    buy_cut = rows_s[int(BUY_PCT * n)][0] if n else None
    cell = [(sh, ex, raw, rfg) for (sh, ex, raw, rfg) in rows
            if rfg is not None and sh >= buy_cut and rfg >= QUALITY_CUT]
    print(f"\n{'='*66}\n  ⭐ STRONG HOLD = top-decile score_hold ∩ QUALITY_HOLD\n{'='*66}")
    if len(cell) < 10:
        print(f"  n={len(cell)} — quá ít để kết luận (cần cả 2 lớp cùng chín).")
        return
    ex = st.mean(x[1] for x in cell)
    wr = sum(1 for x in cell if x[2] > 0) / len(cell)
    print(f"  n={len(cell)}  excess={ex:+.2f}%  winrate>0={wr:.0%}  "
          f"(vs cost {COST_RT:.2f}%)")


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 66)
    print(f"  DIAG HOLD CALIBRATION — track={TRACK}  output={OUTPUT_DIR}")
    print(f"  Ngưỡng pre-register: BUY_PCT={BUY_PCT} AVOID_PCT={AVOID_PCT} "
          f"QUALITY_CUT={QUALITY_CUT} COST={COST_RT}%")
    print("=" * 66)

    ret_map, n_src = build_return_map()
    print("\n  Nguồn return nạp được:")
    for sub, n in n_src.items():
        tag = "native" if sub in NATIVE_OUT else "mượn"
        print(f"    [{tag:>6}] {sub}: {n} record")
    if not ret_map:
        print("  ⚠ Không có sổ outcome nào — chưa thể calibrate. Dừng.")
        return

    preds = load_predictions()
    print(f"\n  Predictions '{PRED_DIR}' daily-last có score_hold: {len(preds)}")
    if not preds:
        print("  ⚠ Ledger predictions trống/thiếu score_hold. Dừng.")
        return

    hits = [(p, ret_map[(p["symbol"], p["signal_date"])])
            for p in preds if (p["symbol"], p["signal_date"]) in ret_map]
    print(f"  Join được (có ≥1 return matured): {len(hits)} obs")

    # Report từng horizon
    for ret_key in ("ret_5d", "ret_10d", "ret_20d"):
        rows = _excess(hits, ret_key)
        report_buy_signal(rows, ret_key)
        report_quality(rows, ret_key)
        report_combined(rows, ret_key)

    print("\n" + "=" * 66)
    print("  DONE. Diag read-only — không ghi file, không đụng production.")
    print("=" * 66)


if __name__ == "__main__":
    main()
