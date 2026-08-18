"""
scripts/diag_finance_vci_coverage.py
====================================
Diagnostic-only. KHÔNG ghi cache, KHÔNG sửa output.

Mục tiêu: xác nhận VCI-only có đủ coverage trên nhiều ngành trước khi đổi production.
Default sample 15 mã đại diện:
  Bank: ACB, VCB, TCB
  Securities: SSI, VND
  Retail/Jewelry: PNJ, MWG
  Industrial/Materials: HPG
  Technology: FPT
  Real estate: VHM, DIG
  Energy: GAS, PVD
  Consumer: VNM
  Airline: VJC

Mỗi mã test:
  - Company(VCI).ratio_summary()
  - Finance(VCI).income_statement(quarter,4)
  - Finance(VCI).balance_sheet(quarter,1)
  - Finance(VCI).cash_flow(year,1)

Ngoài availability, kiểm tra các field scoring tối thiểu trong long-format VCI.
Chạy qua debug.yml input:
  scripts/diag_finance_vci_coverage.py
"""
import os
import sys
import time
from collections import Counter
from importlib import metadata

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"] = "en"
os.environ["MPLCONFIGDIR"] = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock", exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import pandas as pd
from vnstock_data import Finance, Company

DEFAULT_SYMBOLS = [
    "ACB", "VCB", "TCB",
    "SSI", "VND",
    "PNJ", "MWG",
    "HPG", "FPT",
    "VHM", "DIG",
    "GAS", "PVD",
    "VNM", "VJC",
]
SYMBOLS = [s.strip().upper() for s in os.environ.get("DIAG_SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",") if s.strip()]
DELAY = 0.55

# Long-format VCI ids observed from current vnstock_data.
FIELD_ALIASES = {
    "revenue": [
        "IS_NET_REVENUE", "IS_REVENUE", "IS_NET_INTEREST_INCOME",
    ],
    "net_profit": [
        "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY",
        "IS_NET_PROFIT_AFTER_TAX",
        "IS_NET_PROFIT",
    ],
    "total_assets": [
        "BS_TOTAL_ASSETS",
    ],
    "short_assets": [
        "BS_SHORT_TERM_ASSETS",
    ],
    "long_assets": [
        "BS_LONG_TERM_ASSETS",
    ],
    "equity": [
        "BS_OWNER_S_EQUITY", "BS_OWNERS_EQUITY", "BS_TOTAL_EQUITY",
    ],
    "cfo": [
        "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES",
        "CF_NET_CASH_FLOWS_FROM_SECURITIES_TRADING_ACTIVITIES",
    ],
}

RATIO_FIELDS = ["pe", "pb", "roe", "roa"]


def pkg_version(name):
    try:
        return metadata.version(name)
    except Exception:
        return "UNKNOWN"


def safe_call(fn):
    try:
        return fn(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:120]}"
    finally:
        time.sleep(DELAY)


def is_ok_df(df):
    return isinstance(df, pd.DataFrame) and not df.empty


def ids_set(df):
    if not is_ok_df(df) or "id" not in df.columns:
        return set()
    return set(df["id"].dropna().astype(str).tolist())


def has_any_id(df, aliases):
    ids = ids_set(df)
    return any(a in ids for a in aliases)


def ratio_latest_fields(df):
    out = {k: None for k in RATIO_FIELDS}
    if not is_ok_df(df):
        return out
    work = df.copy()
    if "ratio_type" in work.columns:
        ttm = work[work["ratio_type"] == "RATIO_TTM"]
        if not ttm.empty:
            work = ttm
    sort_cols = [c for c in ("year", "quarter") if c in work.columns]
    if sort_cols:
        work = work.sort_values(sort_cols, ascending=False)
    row = work.iloc[0]
    for k in RATIO_FIELDS:
        if k in work.columns:
            v = row.get(k)
            if not pd.isna(v):
                out[k] = v
    return out


def yn(v):
    return "Y" if v else "N"


def main():
    print("=" * 120)
    print("VCI FINANCE BROAD COVERAGE DIAGNOSTIC")
    print(f"symbols({len(SYMBOLS)})={SYMBOLS}")
    for p in ("vnstock", "vnstock_data", "vnai"):
        print(f"{p}={pkg_version(p)}")
    print("READ-ONLY: no cache/output writes")
    print("=" * 120)

    counts = Counter()
    rows = []

    for idx, sym in enumerate(SYMBOLS, 1):
        rs, e_rs = safe_call(lambda: Company(source="VCI", symbol=sym).ratio_summary())
        iq, e_iq = safe_call(lambda: Finance(source="VCI", symbol=sym).income_statement(period="quarter", limit=4))
        bs, e_bs = safe_call(lambda: Finance(source="VCI", symbol=sym).balance_sheet(period="quarter", limit=1))
        cf, e_cf = safe_call(lambda: Finance(source="VCI", symbol=sym).cash_flow(period="year", limit=1))

        api_ratio = is_ok_df(rs)
        api_income = is_ok_df(iq)
        api_balance = is_ok_df(bs)
        api_cf = is_ok_df(cf)

        rf = ratio_latest_fields(rs)
        ratio_core = all(rf[k] is not None for k in RATIO_FIELDS)
        revenue = has_any_id(iq, FIELD_ALIASES["revenue"])
        net_profit = has_any_id(iq, FIELD_ALIASES["net_profit"])
        total_assets = has_any_id(bs, FIELD_ALIASES["total_assets"])
        if not total_assets:
            total_assets = has_any_id(bs, FIELD_ALIASES["short_assets"]) and has_any_id(bs, FIELD_ALIASES["long_assets"])
        equity = has_any_id(bs, FIELD_ALIASES["equity"])
        cfo = has_any_id(cf, FIELD_ALIASES["cfo"])

        minimum_scoring = ratio_core and net_profit and total_assets
        full_scoring = minimum_scoring and revenue and cfo

        flags = {
            "api_ratio": api_ratio,
            "api_income": api_income,
            "api_balance": api_balance,
            "api_cf": api_cf,
            "ratio_core": ratio_core,
            "revenue": revenue,
            "net_profit": net_profit,
            "total_assets": total_assets,
            "equity": equity,
            "cfo": cfo,
            "minimum_scoring": minimum_scoring,
            "full_scoring": full_scoring,
        }
        for k, v in flags.items():
            if v:
                counts[k] += 1

        rows.append((sym, flags, rf))
        print(
            f"[{idx:02d}/{len(SYMBOLS)}] {sym:3s} | "
            f"API R/I/B/CF={yn(api_ratio)}/{yn(api_income)}/{yn(api_balance)}/{yn(api_cf)} | "
            f"PE/PB/ROE/ROA={yn(ratio_core)} | "
            f"REV={yn(revenue)} NP={yn(net_profit)} ASSET={yn(total_assets)} EQ={yn(equity)} CFO={yn(cfo)} | "
            f"MIN={yn(minimum_scoring)} FULL={yn(full_scoring)}"
        )
        if not all((api_ratio, api_income, api_balance, api_cf)):
            errs = [x for x in (e_rs, e_iq, e_bs, e_cf) if x]
            if errs:
                print(f"    errors={errs}")

    n = len(SYMBOLS)
    print("\n" + "=" * 120)
    print("COVERAGE SUMMARY")
    for k in [
        "api_ratio", "api_income", "api_balance", "api_cf",
        "ratio_core", "revenue", "net_profit", "total_assets", "equity", "cfo",
        "minimum_scoring", "full_scoring",
    ]:
        v = counts[k]
        pct = (v / n * 100) if n else 0
        print(f"{k:18s}: {v:2d}/{n} = {pct:6.1f}%")

    print("\nMISSING FIELD DETAIL")
    any_missing = False
    for sym, flags, rf in rows:
        missing = [k for k in ("ratio_core", "revenue", "net_profit", "total_assets", "equity", "cfo") if not flags[k]]
        if missing:
            any_missing = True
            print(f"  {sym}: missing={missing}; ratio={rf}")
    if not any_missing:
        print("  none")

    print("\nDECISION")
    full_pct = counts["full_scoring"] / n * 100 if n else 0
    min_pct = counts["minimum_scoring"] / n * 100 if n else 0
    api_all = min(counts[k] for k in ("api_ratio", "api_income", "api_balance", "api_cf")) if n else 0
    api_pct = api_all / n * 100 if n else 0
    print(f"API all-4 lower-bound coverage: {api_pct:.1f}%")
    print(f"Minimum scoring coverage: {min_pct:.1f}%")
    print(f"Full scoring coverage: {full_pct:.1f}%")
    if api_pct >= 95 and min_pct >= 95:
        print("VCI_ONLY_RECOMMENDATION=PASS")
        if full_pct < 95:
            print("NOTE: some revenue/CFO fields need sector-specific aliases or graceful availability flags.")
    else:
        print("VCI_ONLY_RECOMMENDATION=HOLD")
        print("NOTE: keep multi-source/fallback until missing coverage is understood.")
    print("=" * 120)
    print("DONE — attach this log back to ChatGPT.")


if __name__ == "__main__":
    main()
