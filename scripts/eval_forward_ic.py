#!/usr/bin/env python3
"""
eval_forward_ic.py - Khung danh gia forward SACH cho V4 (Buoc 1).
Sua 3 loi do luong cu:
  1) DAILY-LAST: moi (symbol, signal_date) chi lay 1 snapshot chuan (snap_time muon nhat)
     -> het dem trung ~7x lam phong mau.
  2) IC THEO NGAY roi GOP: tinh Spearman rank-IC trong TUNG ngay, roi lay trung binh +
     khoang tin cay bang BLOCK-BOOTSTRAP theo ngay -> khong pool cheo ngay (chong tu tuong quan).
  3) TACH HORIZON: danh gia rieng 1d/3d/5d/10d.
Read-only: chi doc ledger, khong sua pipeline, khong bump version.

Cach dung:
  python3 scripts/eval_forward_ic.py                       # tat ca version
  python3 scripts/eval_forward_ic.py --version v4.11       # loc 1 version
  python3 scripts/eval_forward_ic.py --score score_trade --horizons 5d 10d
"""
import json, glob, argparse, random, statistics as st
from collections import defaultdict

PRED_GLOB = "output/history/v2f_predictions_v4/*.jsonl"
OUT_GLOB  = "output/history/v2f_outcomes_v4/*.jsonl"

def _f(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def _load(glob_pat):
    rows = []
    for fp in glob.glob(glob_pat):
        for ln in open(fp):
            ln = ln.strip()
            if ln:
                try: rows.append(json.loads(ln))
                except json.JSONDecodeError: pass
    return rows

def _spearman(xs, ys):
    """Rank-IC (Spearman) khong phu thuoc scipy. Tra None neu < 5 diem hoac vo phuong sai."""
    n = len(xs)
    if n < 5: return None
    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0]*n; i = 0
        while i < n:
            j = i
            while j+1 < n and v[order[j+1]] == v[order[i]]: j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j+1): r[order[k]] = avg
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    num = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    dx  = sum((rx[i]-mx)**2 for i in range(n))
    dy  = sum((ry[i]-my)**2 for i in range(n))
    if dx <= 0 or dy <= 0: return None
    return num / (dx*dy) ** 0.5

def daily_last(preds):
    """Giu 1 dong / (symbol, signal_date): snap_time muon nhat."""
    best = {}
    for r in preds:
        k = (r.get("symbol"), r.get("signal_date"))
        st_ = r.get("snap_time") or ""
        if k not in best or st_ > (best[k].get("snap_time") or ""):
            best[k] = r
    return list(best.values())

def block_bootstrap_ci(day_ics, n_boot=2000, alpha=0.05, seed=42):
    """CI cho TRUNG BINH IC theo ngay, resample theo NGAY (moi ngay la 1 block)."""
    days = [d for d, ic in day_ics if ic is not None]
    vals = [ic for d, ic in day_ics if ic is not None]
    if len(vals) < 3: return None
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        samp = [vals[rng.randrange(len(vals))] for _ in range(len(vals))]
        means.append(sum(samp)/len(samp))
    means.sort()
    lo = means[int(alpha/2 * n_boot)]
    hi = means[int((1-alpha/2) * n_boot)]
    return sum(vals)/len(vals), lo, hi

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=None, help="loc scoring_version (vd v4.11)")
    ap.add_argument("--score", default="score_trade", help="cot diem de xep hang")
    ap.add_argument("--horizons", nargs="+", default=["1d","3d","5d","10d"])
    ap.add_argument("--universe", default=None, help="loc universe_variant (vd vn100)")
    args = ap.parse_args()

    preds = _load(PRED_GLOB)
    outs  = _load(OUT_GLOB)
    if not preds or not outs:
        print("Khong co du lieu ledger."); return

    # join outcome theo pred_id
    ret_by_pid = {}
    for o in outs:
        pid = o.get("pred_id")
        if pid:
            ret_by_pid[pid] = o

    # loc + daily-last
    if args.version:
        preds = [p for p in preds if p.get("scoring_version") == args.version]
    if args.universe:
        preds = [p for p in preds if p.get("universe_variant") == args.universe]
    preds = daily_last(preds)

    print("=== EVAL FORWARD IC (daily-last, IC theo ngay + block-bootstrap) ===")
    print("score = %s | version = %s | universe = %s" % (args.score, args.version or "TAT CA", args.universe or "TAT CA"))
    print("predictions (sau daily-last): %d" % len(preds))

    for hz in args.horizons:
        ret_key = "ret_" + hz
        # gom theo ngay
        by_day = defaultdict(lambda: ([], []))
        matured = 0
        for p in preds:
            o = ret_by_pid.get(p.get("pred_id"))
            if not o: continue
            sc = _f(p.get(args.score)); rt = _f(o.get(ret_key))
            if sc is None or rt is None: continue
            xs, ys = by_day[p.get("signal_date")]
            xs.append(sc); ys.append(rt); matured += 1
        # IC moi ngay
        day_ics = []
        for d in sorted(by_day):
            xs, ys = by_day[d]
            ic = _spearman(xs, ys)
            day_ics.append((d, ic))
        valid = [(d, ic) for d, ic in day_ics if ic is not None]
        print("\n-- horizon %s --" % hz)
        print("  quan sat da chin: %d | so ngay co IC: %d" % (matured, len(valid)))
        if valid:
            ci = block_bootstrap_ci(day_ics)
            mean_ic = sum(ic for _, ic in valid)/len(valid)
            line = "  IC trung binh theo ngay: %+.4f" % mean_ic
            if ci:
                _, lo, hi = ci
                sig = "" if (lo <= 0 <= hi) else "  *khac 0 (95%)"
                line += "  | CI95 [%+.4f, %+.4f]%s" % (lo, hi, sig)
            print(line)
            # hien vai ngay gan nhat
            for d, ic in valid[-5:]:
                print("     %s  IC=%+.4f" % (d, ic))
        else:
            print("  chua du ngay chin de tinh IC (can >=5 ma/ngay va >=3 ngay).")

if __name__ == "__main__":
    main()
