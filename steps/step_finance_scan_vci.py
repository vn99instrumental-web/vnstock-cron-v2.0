"""
step_finance_scan_vci.py — VCI-only finance cache builder (candidate)
====================================================================
Purpose
-------
Candidate replacement for steps/step_finance_scan.py after vnstock_data 3.2.8
schema migration.

Key design:
  - Ratio: Company(source="VCI").ratio_summary()
  - Statements: Finance(source="VCI") long format:
        period | id | name | order | level | unit | value
  - Taxonomy IDs are based on vnstock_3.2.8_schema_migration_reference.csv.
  - Keeps the current cache/output contract:
        ratio, income, balance, cashflow, data_status, finance_score
    so V2/V3/V4 downstream code does not need to change.
  - Empty finance response is a fetch failure, NEVER inferred as non_stock.
  - Last-known-good cache is preserved on refresh failure.
  - Writes production output/finance/cache.json (VCI-only builder).
"""

import os
import re
import sys
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"] = "en"
os.environ["MPLCONFIGDIR"] = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock", exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

from vnstock_data import Finance, Company, Listing
from utils.helpers import now_ict, to_float
from utils.cache import load_json, save_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------

MAX_SYMBOLS = 150
MAX_WORKERS = 2
API_CALL_DELAY = 0.40

EARNINGS_MONTHS = {1, 2, 4, 5, 7, 8, 10, 11}
TTL_EARNINGS = 3
TTL_NORMAL = 30

# Production cache (VCI-only builder replacing KBS-based step_finance_scan.py).
CACHE_FILE = "finance/cache.json"
SCHEMA_VERSION = 9
SOURCE = "VCI"

_NON_STOCK_PATTERN = re.compile(
    r"^(VN30F|VNINDEX|HNXINDEX|HNX30|VHNDEX|E1|FUED|FUEV|SSIAM|DCDS)",
    re.IGNORECASE,
)
_VALID_EXCHANGES = {"HSX", "HOSE", "HNX", "HSX (HOSE)"}
_CORE_INDEX_GROUPS = ["VN100", "HNX30"]
_FILL_INDEX_GROUP = "VNSML"

# ---------------------------------------------------------------------
# vnstock_data 3.2.8 taxonomy IDs
# Generated from vnstock_3.2.8_schema_migration_reference.csv
# ---------------------------------------------------------------------

# Generic top-line metric. Priority matters:
# normal corporates -> net revenue/revenue;
# banks/securities -> total operating income / net interest income;
# insurance -> total net insurance revenue.
_REVENUE_IDS = [
    "IS_NET_REVENUE",
    "IS_REVENUE",
    "IS_TOTAL_OPERATING_INCOME",
    "IS_NET_INTEREST_INCOME",
    "IS_TOTAL_NET_REVENUE_FROM_INSURANCE_BUSINESS",
]

_NET_PROFIT_IDS = [
    "IS_PROFIT_AFTER_TAX_FOR_SHAREHOLDERS_OF_PARENT_COMPANY",
    "IS_NET_PROFIT_AFTER_TAX",
]

_GROSS_PROFIT_IDS = [
    "IS_GROSS_PROFIT",
    "IS_GROSS_INSURANCE_OPERATING_PROFIT",
]

_OPERATING_PROFIT_IDS = [
    "IS_OPERATING_PROFIT",
    "IS_OPERATING_PROFIT_BEFORE_PROVISION_FOR_CREDIT_LOSSES",
    "IS_NET_PROFIT_BANKING_ACTIVITY",
]

_EPS_IDS = [
    "IS_BASIC_EARNINGS_PER_SHARE",
    "IS_DILUTED_EARNINGS_PER_SHARE",
]

_TOTAL_ASSETS_IDS = ["BS_TOTAL_ASSETS"]
_SHORT_ASSETS_IDS = ["BS_SHORT_TERM_ASSETS"]
_LONG_ASSETS_IDS = ["BS_LONG_TERM_ASSETS"]
_EQUITY_IDS = ["BS_EQUITY", "BS_OWNERS_EQUITY"]
_TOTAL_LIAB_IDS = ["BS_TOTAL_LIABILITIES"]
_SHORT_DEBT_IDS = ["BS_SHORT_TERM_BORROWINGS", "BS_SHORT_TERM_BORROWINGS_DETAIL"]
_LONG_DEBT_IDS = ["BS_LONG_TERM_BORROWINGS"]

_CFO_IDS = [
    "CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES",
]
_CFI_IDS = [
    "CF_NET_CASH_FLOWS_FROM_INVESTING_ACTIVITIES",
]
_CFF_IDS = [
    "CF_NET_CASH_FLOWS_FROM_FINANCING_ACTIVITIES",
    # Some legacy taxonomy rows map "cash flows during the period" to old KBS
    # financing aliases. Keep only as last-resort fallback.
    "CF_NET_CASH_FLOWS_DURING_THE_PERIOD",
]

# ---------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------

def _is_valid_stock(symbol: str, asset_type: str | None = None) -> bool:
    if not symbol or len(symbol) < 2 or len(symbol) > 5:
        return False
    if _NON_STOCK_PATTERN.match(symbol):
        return False
    if symbol.startswith("X"):
        return False
    if re.search(r"[0-9]{3,}", symbol):
        return False
    if asset_type is not None:
        return str(asset_type).lower() in {"stock", "s", "equity"}
    return True


def _current_ttl_days() -> int:
    return TTL_EARNINGS if now_ict().month in EARNINGS_MONTHS else TTL_NORMAL


def _is_stale(entry: dict | None) -> bool:
    if not entry:
        return True

    # Legacy poison protection: authoritative stock universe must be revalidated.
    if entry.get("non_stock"):
        return True

    if entry.get("schema_version", 0) < SCHEMA_VERSION:
        return True
    if "finance_score" not in entry:
        return True

    fetched_at = entry.get("fetched_at")
    if not fetched_at:
        return True
    try:
        dt = datetime.fromisoformat(fetched_at)
        age_days = (now_ict() - dt).total_seconds() / 86400
        return age_days > _current_ttl_days()
    except Exception:
        return True


def _num(v):
    """Safe numeric scalar."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return to_float(v)


def _pct(v):
    """ratio_summary percentages are usually decimals; normalize to percent."""
    v = _num(v)
    if v is None:
        return None
    if v == 0:
        return 0.0
    return v * 100 if abs(v) < 1 else v


def _period_key(period) -> tuple[int, int]:
    """
    Sort key for common VCI period strings:
      2026-Q2 -> (2026, 2)
      2025    -> (2025, 0)
    Unknown formats sort lowest.
    """
    s = str(period or "").strip().upper()
    m = re.match(r"^(\d{4})[-_/ ]?Q([1-4])$", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d{4})$", s)
    if m:
        return int(m.group(1)), 0
    return -1, -1


def _long_rows(df: pd.DataFrame | None, ids: list[str]) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    if not {"id", "value"}.issubset(df.columns):
        return pd.DataFrame()
    work = df[df["id"].astype(str).isin(ids)].copy()
    if work.empty:
        return work
    if "period" not in work.columns:
        work["period"] = ""
    # vnstock_data 3.2.8 trả 'period' kiểu Categorical. Series.map() trên
    # Categorical với mapper trả tuple -> pandas dựng MultiIndex -> sort_values
    # ném "NotImplementedError: isna is not defined for MultiIndex".
    # Cách né: ép period về object, tách year/quarter thành 2 cột số vô hướng.
    periods = work["period"].astype(object).tolist()
    keys = [_period_key(p) for p in periods]
    work["_period_year"] = [k[0] for k in keys]
    work["_period_quarter"] = [k[1] for k in keys]
    work = work.sort_values(
        ["_period_year", "_period_quarter"], ascending=[False, False]
    )
    return work


def _long_lookup(df: pd.DataFrame | None, ids: list[str]) -> float | None:
    """
    Return latest non-null numeric value for the first taxonomy ID that exists.
    Alias priority follows `ids`.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None

    for tax_id in ids:
        rows = _long_rows(df, [tax_id])
        if rows.empty:
            continue
        for v in rows["value"].tolist():
            n = _num(v)
            if n is not None:
                return n
    return None


def _long_metric_series(df: pd.DataFrame | None, ids: list[str]) -> tuple[str | None, list[tuple[str, float]]]:
    """
    Pick first available taxonomy ID and return unique period/value pairs,
    sorted newest -> oldest.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None, []

    for tax_id in ids:
        rows = _long_rows(df, [tax_id])
        if rows.empty:
            continue

        out = []
        seen = set()
        for _, row in rows.iterrows():
            period = str(row.get("period", ""))
            if period in seen:
                continue
            val = _num(row.get("value"))
            if val is None:
                continue
            seen.add(period)
            out.append((period, val))

        if out:
            return tax_id, out

    return None, []


def _qoq_growth(df: pd.DataFrame | None, ids: list[str]) -> tuple[float | None, str | None]:
    tax_id, series = _long_metric_series(df, ids)
    if len(series) < 2:
        return None, tax_id
    latest = series[0][1]
    prev = series[1][1]
    if prev == 0:
        return None, tax_id
    return round((latest - prev) / abs(prev), 4), tax_id


def _yoy_growth(df: pd.DataFrame | None, ids: list[str]) -> tuple[float | None, str | None]:
    tax_id, series = _long_metric_series(df, ids)
    if not series:
        return None, tax_id

    latest_period, latest = series[0]
    y, q = _period_key(latest_period)
    if y < 0 or q <= 0:
        return None, tax_id

    target = (y - 1, q)
    for period, value in series[1:]:
        if _period_key(period) == target:
            if value == 0:
                return None, tax_id
            return round((latest - value) / abs(value), 4), tax_id

    return None, tax_id


# ---------------------------------------------------------------------
# Ratio summary
# ---------------------------------------------------------------------

def _fetch_ratio_summary(symbol: str) -> tuple[dict, str]:
    df = Company(source=SOURCE, symbol=symbol).ratio_summary()
    if df is None or df.empty:
        return {}, ""

    work = df.copy()
    if "ratio_type" in work.columns:
        ttm = work[work["ratio_type"] == "RATIO_TTM"]
        if not ttm.empty:
            work = ttm

    sort_cols = [c for c in ("year", "quarter") if c in work.columns]
    if sort_cols:
        work = work.sort_values(sort_cols, ascending=False)

    row = work.iloc[0]

    def get(col):
        if col not in work.columns:
            return None
        return _num(row.get(col))

    ratio = {
        "pe": get("pe"),
        "pb": get("pb"),
        "roe": _pct(get("roe")),
        "roa": _pct(get("roa")),
        "eps": get("eps"),
        "bvps": get("bvps"),
        "beta": get("beta"),
        "div_yield": _pct(get("dividend_yield")),
        "gross_margin": _pct(get("gross_margin")),
        "net_margin": _pct(get("after_tax_profit_margin")),
        "quick_ratio": get("quick_ratio"),
        "interest_cov": get("interest_coverage"),
        "ev_ebitda": get("ev_to_ebitda"),
    }

    period = ""
    year = row.get("year") if "year" in work.columns else None
    qtr = row.get("quarter") if "quarter" in work.columns else None
    try:
        if year is not None and not pd.isna(year):
            period = str(int(year))
            if qtr is not None and not pd.isna(qtr) and int(qtr) > 0:
                period += f"-Q{int(qtr)}"
    except Exception:
        period = ""

    return ratio, period


# ---------------------------------------------------------------------
# Scoring contract — intentionally preserved from current production
# ---------------------------------------------------------------------

def _compute_finance_score(data: dict) -> dict:
    s = {}

    r = data.get("ratio", {}) or {}
    pe = r.get("pe")
    pb = r.get("pb")
    roe = r.get("roe")

    fund = 0
    if pe is not None and pe > 0:
        if pe < 10:
            fund += 10
        elif pe < 15:
            fund += 7
        elif pe <= 25:
            fund += 3
        else:
            fund -= 5
    elif pe is not None and pe < 0:
        fund -= 5

    if pb is not None and pb > 0:
        if pb < 1:
            fund += 5
        elif pb <= 2:
            fund += 3
        elif pb <= 3:
            fund += 0
        else:
            fund -= 3
    elif pb is not None and pb < 0:
        fund -= 5

    if roe is not None:
        if roe > 20:
            fund += 5
        elif roe > 15:
            fund += 3
        elif roe > 10:
            fund += 0
        elif roe < 5:
            fund -= 3

    s["fundamental"] = max(-18, min(18, fund))

    c = data.get("cashflow", {}) or {}
    cfo = c.get("cf_operating")
    cfq = c.get("cf_quality")

    cf = 0
    if cfo is not None:
        cf += 5 if cfo > 0 else -10
    if cfq is not None:
        if cfq > 1:
            cf += 5
        elif cfq < 0.5:
            cf -= 5
    s["cashflow"] = max(-10, min(10, cf))

    i = data.get("income", {}) or {}
    rev_g = i.get("rev_growth_qoq")
    np_g = i.get("profit_growth_qoq")

    growth = 0
    if rev_g is not None:
        if rev_g > 0.20:
            growth += 5
        elif rev_g > 0.10:
            growth += 3
        elif rev_g > 0:
            growth += 1
        elif rev_g < -0.10:
            growth -= 3
        else:
            growth -= 1

    if np_g is not None:
        if np_g > 0.20:
            growth += 5
        elif np_g > 0.10:
            growth += 3
        elif np_g > 0:
            growth += 1
        elif np_g < -0.10:
            growth -= 3
        else:
            growth -= 1

    s["growth"] = max(-10, min(10, growth))
    s["total"] = s["fundamental"] + s["cashflow"] + s["growth"]
    s["max"] = 38
    return s


# ---------------------------------------------------------------------
# Fetch one symbol
# ---------------------------------------------------------------------

def fetch_one(symbol: str, asset_type: str | None = None) -> dict | None:
    if not _is_valid_stock(symbol, asset_type):
        return None

    result = {
        "symbol": symbol,
        "fetched_at": now_ict().isoformat(),
        "schema_version": SCHEMA_VERSION,
        "period": "",
        "ratio": {},
        "income": {},
        "balance": {},
        "cashflow": {},
        "data_status": {
            "ratio_source": None,
            "statement_source": None,
            "cf_available": False,
            "growth_available": False,
            "incomplete": True,
            "revenue_metric_id": None,
            "profit_metric_id": None,
        },
    }

    # 1) Ratio summary
    try:
        ratio, period = _fetch_ratio_summary(symbol)
        result["ratio"] = ratio
        result["period"] = period
        if any(v is not None for v in ratio.values()):
            result["data_status"]["ratio_source"] = "vci_ratio_summary"
    except Exception as e:
        log.warning(f"  ⚠️ ratio_summary {symbol}: {type(e).__name__}: {e}")
    time.sleep(API_CALL_DELAY)

    # 2) Quarterly income
    df_iq = None
    try:
        df_iq = Finance(source=SOURCE, symbol=symbol).income_statement(
            period="quarter", limit=8
        )
    except Exception as e:
        log.warning(f"  ⚠️ income_q {symbol}: {type(e).__name__}: {e}")
    time.sleep(API_CALL_DELAY)

    if isinstance(df_iq, pd.DataFrame) and not df_iq.empty:
        i = result["income"]
        i["revenue"] = _long_lookup(df_iq, _REVENUE_IDS)
        i["gross_profit"] = _long_lookup(df_iq, _GROSS_PROFIT_IDS)
        i["net_profit"] = _long_lookup(df_iq, _NET_PROFIT_IDS)
        i["operating_profit"] = _long_lookup(df_iq, _OPERATING_PROFIT_IDS)
        i["eps"] = _long_lookup(df_iq, _EPS_IDS)

        rev_qoq, rev_id = _qoq_growth(df_iq, _REVENUE_IDS)
        np_qoq, np_id = _qoq_growth(df_iq, _NET_PROFIT_IDS)
        rev_yoy, _ = _yoy_growth(df_iq, _REVENUE_IDS)
        np_yoy, _ = _yoy_growth(df_iq, _NET_PROFIT_IDS)

        i["rev_growth_qoq"] = rev_qoq
        i["profit_growth_qoq"] = np_qoq
        i["rev_growth_yoy"] = rev_yoy
        i["profit_growth_yoy"] = np_yoy

        result["data_status"]["statement_source"] = "vci_long"
        result["data_status"]["revenue_metric_id"] = rev_id
        result["data_status"]["profit_metric_id"] = np_id
        result["data_status"]["growth_available"] = (
            rev_qoq is not None or np_qoq is not None
        )

    # 3) Balance sheet
    df_bs = None
    try:
        df_bs = Finance(source=SOURCE, symbol=symbol).balance_sheet(
            period="quarter", limit=1
        )
    except Exception as e:
        log.warning(f"  ⚠️ balance_q {symbol}: {type(e).__name__}: {e}")
    time.sleep(API_CALL_DELAY)

    if isinstance(df_bs, pd.DataFrame) and not df_bs.empty:
        b = result["balance"]

        total_assets = _long_lookup(df_bs, _TOTAL_ASSETS_IDS)
        if total_assets is None:
            short_assets = _long_lookup(df_bs, _SHORT_ASSETS_IDS)
            long_assets = _long_lookup(df_bs, _LONG_ASSETS_IDS)
            if short_assets is not None and long_assets is not None:
                total_assets = short_assets + long_assets

        b["total_assets"] = total_assets
        b["equity"] = _long_lookup(df_bs, _EQUITY_IDS)
        b["total_liab"] = _long_lookup(df_bs, _TOTAL_LIAB_IDS)
        b["short_debt"] = _long_lookup(df_bs, _SHORT_DEBT_IDS)
        b["long_debt"] = _long_lookup(df_bs, _LONG_DEBT_IDS)

        if b["equity"] not in (None, 0):
            if b["total_liab"] is not None:
                b["debt_to_equity"] = round(b["total_liab"] / b["equity"], 3)
            elif total_assets is not None:
                b["debt_to_equity"] = round(
                    (total_assets - b["equity"]) / b["equity"], 3
                )

    # 4) Annual cash flow
    df_cf = None
    try:
        df_cf = Finance(source=SOURCE, symbol=symbol).cash_flow(
            period="year", limit=2
        )
    except Exception as e:
        log.warning(f"  ⚠️ cashflow_y {symbol}: {type(e).__name__}: {e}")
    time.sleep(API_CALL_DELAY)

    if isinstance(df_cf, pd.DataFrame) and not df_cf.empty:
        c = result["cashflow"]
        c["cf_operating"] = _long_lookup(df_cf, _CFO_IDS)
        c["cf_investing"] = _long_lookup(df_cf, _CFI_IDS)
        c["cf_financing"] = _long_lookup(df_cf, _CFF_IDS)
        c["cf_period"] = "annual"

        if c["cf_operating"] is not None and c["cf_investing"] is not None:
            c["cf_free"] = round(c["cf_operating"] + c["cf_investing"], 2)

        result["data_status"]["cf_available"] = c["cf_operating"] is not None

    # 5) Annual income for CFO / annual net profit quality
    df_iy = None
    try:
        df_iy = Finance(source=SOURCE, symbol=symbol).income_statement(
            period="year", limit=2
        )
    except Exception as e:
        log.warning(f"  ⚠️ income_y {symbol}: {type(e).__name__}: {e}")
    time.sleep(API_CALL_DELAY)

    if isinstance(df_iy, pd.DataFrame) and not df_iy.empty:
        net_profit_year = _long_lookup(df_iy, _NET_PROFIT_IDS)
        result["income"]["net_profit_year"] = net_profit_year

        cfo = result["cashflow"].get("cf_operating")
        if cfo is not None and net_profit_year not in (None, 0):
            result["cashflow"]["cf_quality"] = round(cfo / net_profit_year, 2)
            result["cashflow"]["cf_quality_period"] = "annual"

    # Important: data presence != stock classification.
    has_data = any(
        v is not None
        for v in [
            result["ratio"].get("pe"),
            result["ratio"].get("roe"),
            result["income"].get("revenue"),
            result["income"].get("net_profit"),
            result["balance"].get("total_assets"),
            result["cashflow"].get("cf_operating"),
        ]
    )
    if not has_data:
        log.warning(
            f"  [{symbol}] VCI finance returned no usable fields — fetch failure; "
            "cache will not be overwritten"
        )
        return None

    status = result["data_status"]
    status["incomplete"] = (
        status["ratio_source"] is None
        or result["income"].get("net_profit") is None
        or result["balance"].get("total_assets") is None
        or not status["cf_available"]
    )

    result["finance_score"] = _compute_finance_score(result)
    return result


# ---------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------

def load_cache() -> dict:
    data = load_json(CACHE_FILE)
    if not data:
        return {}
    if isinstance(data, dict) and "symbols" in data:
        return data["symbols"]
    if isinstance(data, dict):
        return data
    return {}


def save_cache(symbols_dict: dict) -> None:
    save_json(
        CACHE_FILE,
        {
            "generated_at": now_ict().isoformat(),
            "schema_version": SCHEMA_VERSION,
            "source": SOURCE,
            "ttl_days": _current_ttl_days(),
            "count": len(symbols_dict),
            "symbols": symbols_dict,
        },
    )


# ---------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------

def _fetch_index_members(group: str) -> list[str]:
    try:
        res = Listing(source=SOURCE).symbols_by_group(group=group)
    except Exception as e:
        log.warning(f"  ⚠️ symbols_by_group({group}) failed: {type(e).__name__}")
        return []

    if res is None:
        return []
    if isinstance(res, pd.Series):
        syms = res.dropna().astype(str).tolist()
    elif isinstance(res, pd.DataFrame):
        if res.empty:
            return []
        col = "symbol" if "symbol" in res.columns else res.columns[0]
        syms = res[col].dropna().astype(str).tolist()
    elif isinstance(res, (list, tuple)):
        syms = [str(x) for x in res]
    else:
        return []

    return [s.strip().upper() for s in syms if s and s.strip()]


def _industry_map_symbols(industry_map: list) -> list[str]:
    out = []
    for row in industry_map:
        sym = row.get("symbol") or row.get("ticker") or row.get("code")
        if not sym:
            continue
        exchange = (row.get("exchange") or "").upper().strip()
        if exchange and exchange not in _VALID_EXCHANGES:
            continue
        asset_type = row.get("type") or row.get("asset_type")
        if not _is_valid_stock(sym, asset_type):
            continue
        out.append(str(sym).strip().upper())
    return out


def get_scan_universe(industry_map: list) -> list[str]:
    seen = set()
    universe = []

    def add(syms: list[str], label: str):
        added = 0
        for s in syms:
            if len(universe) >= MAX_SYMBOLS:
                break
            if _is_valid_stock(s) and s not in seen:
                seen.add(s)
                universe.append(s)
                added += 1
        log.info(f"  + {label}: +{added} (total {len(universe)})")

    for grp in _CORE_INDEX_GROUPS:
        add(_fetch_index_members(grp), grp)
    core_count = len(universe)

    if len(universe) < MAX_SYMBOLS:
        add(_fetch_index_members(_FILL_INDEX_GROUP), _FILL_INDEX_GROUP)
    if len(universe) < MAX_SYMBOLS:
        add(_industry_map_symbols(industry_map), "industry_map")

    if not universe:
        add(_industry_map_symbols(industry_map), "industry_map(fallback)")

    log.info(
        f"Universe: {len(universe)} symbols "
        f"(core VN100+HNX30={core_count}, fill={len(universe) - core_count})"
    )
    return universe


# ---------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------

def run(extra_symbols: list[str] | None = None) -> dict:
    log.info("=== step_finance_scan_vci: START ===")
    log.info(
        f"source={SOURCE}, schema={SCHEMA_VERSION}, workers={MAX_WORKERS}, "
        f"TTL={_current_ttl_days()}d"
    )

    industry_map = load_json("industry_map.json") or []
    if not industry_map:
        log.error("industry_map.json not found — run step3_context.py first")
        return {}

    universe = get_scan_universe(industry_map)
    if extra_symbols:
        for s in extra_symbols:
            s = str(s).strip().upper()
            if _is_valid_stock(s) and s not in universe:
                universe.append(s)

    cache = load_cache()

    # Candidate cache could still receive poison from copied/manual data.
    purged = 0
    for sym in universe:
        if (cache.get(sym) or {}).get("non_stock"):
            cache.pop(sym, None)
            purged += 1
    if purged:
        log.warning(f"Purged {purged} legacy non_stock entries")

    to_fetch = [s for s in universe if _is_stale(cache.get(s))]
    to_skip = [s for s in universe if s not in to_fetch]
    log.info(f"Fetch: {len(to_fetch)}, Skip: {len(to_skip)}")

    if not to_fetch:
        log.info("All symbols fresh — candidate cache unchanged")
        return cache

    ok = 0
    failed = 0
    incomplete = 0
    last_good_kept = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_one, sym): sym for sym in to_fetch}

        for future in as_completed(futures):
            sym = futures[future]
            old = cache.get(sym)

            try:
                result = future.result()
            except Exception as e:
                result = None
                log.error(f"  ❌ {sym}: {type(e).__name__}: {e}")

            if result is None:
                failed += 1
                if old and not old.get("non_stock"):
                    last_good_kept += 1
                    log.warning(f"  ⚠️ {sym}: refresh failed — kept last-known-good")
                else:
                    log.warning(f"  ⚠️ {sym}: refresh failed — no prior good entry")
                continue

            cache[sym] = result
            ok += 1
            if (result.get("data_status") or {}).get("incomplete"):
                incomplete += 1

            fs = result.get("finance_score") or {}
            ds = result.get("data_status") or {}
            log.info(
                f"  ✅ {sym} PE={result['ratio'].get('pe')} "
                f"ROE={result['ratio'].get('roe')} "
                f"CFO={result['cashflow'].get('cf_operating')} "
                f"score={fs.get('total')} "
                f"rev_id={ds.get('revenue_metric_id')} "
                f"incomplete={ds.get('incomplete')}"
            )

    save_cache(cache)

    covered = sum(
        1
        for s in universe
        if cache.get(s)
        and not cache[s].get("non_stock")
        and cache[s].get("finance_score") is not None
    )
    coverage_pct = round(covered / len(universe) * 100, 1) if universe else 0.0

    log.info(
        f"Done: {ok} refreshed, {failed} failed, {incomplete} incomplete, "
        f"{last_good_kept} last-good kept, {len(to_skip)} skipped. "
        f"Coverage={covered}/{len(universe)} ({coverage_pct}%)."
    )
    log.info(f"Candidate cache: output/{CACHE_FILE}")
    log.info("=== step_finance_scan_vci: DONE ===")
    return cache


if __name__ == "__main__":
    run()
