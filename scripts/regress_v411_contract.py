#!/usr/bin/env python3
"""
Regression + impact report cho v4.11 defect-fix (hop dong factor).
Read-only: doc output/v2f_signals.json (base V2) + output/v2f_signals_v4.json (ground truth cu).
Chung minh: (1) ma DAT khong con duoc thuong fundamental, (2) growth/ff dung het span,
            (3) cong thuc CU khop s_fund_core (sanity), roi in Delta tac dong.
Exit != 0 neu bat ky assertion nao fail -> dung lam CI gate.
"""
import json, sys, statistics as st

def _f(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0

def _renorm(v, true_max, span):
    v = _f(v)
    if true_max <= 0: return 0
    v = max(-true_max, min(true_max, v))
    return int(round(v / true_max * span))

# -- cong thuc CU (v4.10) vs MOI (v4.11) --
def sc_fund_old(r):   return _renorm(_f(r.get("fundamental_score")) - _f(r.get("ext_fv_score")), 23, 8)
def sc_fund_new(r):   return _renorm(_f(r.get("fundamental_score")), 20, 8)
def sc_growth_old(r): return _renorm(r.get("growth_score"), 15, 5)
def sc_growth_new(r): return _renorm(r.get("growth_score"), 10, 5)
def sc_ff_old(r):     return _renorm(r.get("ff_score"), 18, 6)
def sc_ff_new(r):     return _renorm(r.get("ff_score"), 15, 6)
def sc_ctx_old(r):    return _renorm(_f(r.get("context_score")) - _f(r.get("ext_breadth_score")), 5, 2)
def sc_ctx_new(r):    return _renorm(_f(r.get("context_score")), 5, 2)

def main():
    v2 = json.load(open("output/v2f_signals.json"))
    v4 = {r["symbol"]: r for r in json.load(open("output/v2f_signals_v4.json"))}
    fails = []

    # SANITY: cong thuc CU phai khop s_fund_core ground truth
    mismatch = 0
    for r in v2:
        gt = v4.get(r["symbol"], {}).get("s_fund_core")
        if gt is not None and sc_fund_old(r) != int(gt):
            mismatch += 1
    if mismatch:
        fails.append(f"SANITY sc_fund_old lech s_fund_core: {mismatch} ma")
    else:
        print(f"[OK] SANITY: sc_fund_old khop s_fund_core {len(v2)}/{len(v2)}")

    # ASSERT 1: ma DAT (ext_fv<0) -- sc_fund MOI phai <= CU (khong con thuong oan)
    bad = [r["symbol"] for r in v2 if _f(r.get("ext_fv_score")) < 0 and sc_fund_new(r) > sc_fund_old(r)]
    if bad:
        fails.append(f"ASSERT1 ma dat van tang diem: {bad[:10]}")
    else:
        print(f"[OK] ASSERT1: {sum(1 for r in v2 if _f(r.get('ext_fv_score'))<0)} ma dat khong con duoc thuong oan")

    # ASSERT 2: growth_score==10 phai cho span day 5 (cu chi 3)
    g10 = [r for r in v2 if _f(r.get("growth_score")) >= 10]
    if g10 and any(sc_growth_new(r) < 5 for r in g10):
        fails.append("ASSERT2 growth cap chua dung het span 5")
    else:
        print(f"[OK] ASSERT2: growth span day (ma growth>=10: {len(g10)}, cu toi da {max([sc_growth_old(r) for r in g10], default=0)}/5 -> moi 5/5)")

    # ASSERT 3: |ff|>=15 phai cho span day 6 (cu chi 5)
    ff15 = [r for r in v2 if abs(_f(r.get("ff_score"))) >= 15]
    if ff15 and any(abs(sc_ff_new(r)) < 6 for r in ff15):
        fails.append("ASSERT3 ff cap chua dung het span 6")
    else:
        print(f"[OK] ASSERT3: ff span day (ma |ff|>=15: {len(ff15)}, cu toi da {max([abs(sc_ff_old(r)) for r in ff15], default=0)}/6 -> moi 6/6)")

    # ASSERT 4: context khong doi khi breadth=0 (an toan hien tai)
    if any(sc_ctx_new(r) != sc_ctx_old(r) for r in v2 if _f(r.get("ext_breadth_score")) == 0):
        fails.append("ASSERT4 context doi du breadth=0 (khong ky vong)")
    else:
        print("[OK] ASSERT4: context bat bien khi breadth=0")

    # IMPACT (diem tin hieu tho, span-level; decision phai rerun full engine)
    d_f = [sc_fund_new(r)   - sc_fund_old(r)   for r in v2]
    d_g = [sc_growth_new(r) - sc_growth_old(r) for r in v2]
    d_x = [sc_ff_new(r)     - sc_ff_old(r)     for r in v2]
    print("\n-- IMPACT diem tin hieu (span) -- decision can rerun full engine --")
    for name, d in (("sc_fund", d_f), ("sc_growth", d_g), ("sc_ff", d_x)):
        chg = sum(1 for x in d if x != 0)
        print(f"  {name:10s} Dmean {st.mean(d):+.2f}  Dmedian {st.median(d):+.2f}  min/max {min(d):+d}/{max(d):+d}  doi {chg}/{len(d)} ma")

    if fails:
        print("\nX REGRESSION FAIL:")
        for m in fails: print("   -", m)
        sys.exit(1)
    print("\nOK REGRESSION PASS -- an toan de rerun full engine + commit v4.11")

if __name__ == "__main__":
    main()
