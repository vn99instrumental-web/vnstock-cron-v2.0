"""
step_finance_scan.py — Production finance adapter for vnstock_data 3.2.8
========================================================================
Production entrypoint used by cron_daily.yml and lazy intraday finance fetch.

The validated VCI implementation lives in step_finance_scan_vci.py. This
adapter applies the production-safe schema fixes confirmed on 5 symbols and
then on the full 150-symbol universe, while preserving the existing cache
contract consumed by V2/V3/V4.

Schema v9 fixes:
  1) VCI-only finance source.
  2) Long-format period/id/value parser.
  3) pandas Categorical period fix: scalar year/quarter sorting, no tuple map.
  4) Sector-aware top-line taxonomy priority.
  5) Correct CFF taxonomy only; no "net cash flows during period" fallback.
  6) No inferred Total Assets from short + long assets.
  7) Empty finance response is fetch failure, never non_stock.
  8) Last-known-good cache preserved on refresh failure.
  9) Richer data_status / missing_fields observability.

NOTE:
  - Ratio remains Company(VCI).ratio_summary() in this production phase.
  - Statements use Finance(VCI) vnstock_data 3.2.8 long format.
  - Output remains output/finance/cache.json.
"""

import pandas as pd

from steps import step_finance_scan_vci as _vci

# ---------------------------------------------------------------------------
# Production configuration
# ---------------------------------------------------------------------------

_vci.CACHE_FILE = "finance/cache.json"
_vci.SCHEMA_VERSION = 9
_vci.SOURCE = "VCI"
_vci.MAX_WORKERS = 2
_vci.API_CALL_DELAY = 0.40

# Prefer sector-specific top-line IDs before generic corporate revenue.
_vci._REVENUE_IDS = [
    "IS_TOTAL_NET_REVENUE_FROM_INSURANCE_BUSINESS",
    "IS_TOTAL_OPERATING_INCOME",
    "IS_NET_INTEREST_INCOME",
    "IS_NET_REVENUE",
    "IS_REVENUE",
]

# Migration reference confirms these are distinct concepts.
_vci._CFF_IDS = [
    "CF_NET_CASH_FLOWS_FROM_FINANCING_ACTIVITIES",
]

# Disable unsafe Total Assets reconstruction fallback.
# step_finance_scan_vci first tries BS_TOTAL_ASSETS; if unavailable it then
# looks up these lists. Empty/nonexistent IDs force a graceful None instead
# of inferring Total Assets from ambiguous components.
_vci._SHORT_ASSETS_IDS = ["__DISABLED_SHORT_ASSETS_FALLBACK__"]
_vci._LONG_ASSETS_IDS = ["__DISABLED_LONG_ASSETS_FALLBACK__"]


# ---------------------------------------------------------------------------
# Proven pandas Categorical period fix
# ---------------------------------------------------------------------------

def _fixed_long_rows(
    df: pd.DataFrame | None,
    ids: list[str],
) -> pd.DataFrame:
    """
    Filter long-format VCI rows and sort newest first.

    vnstock_data 3.2.8 can return `period` as pandas Categorical.
    Mapping tuple keys directly onto that Categorical caused:
      NotImplementedError: isna is not defined for MultiIndex

    Convert period to plain Python objects and sort on scalar year/quarter.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()

    if not {"id", "value"}.issubset(df.columns):
        return pd.DataFrame()

    work = df[df["id"].astype(str).isin(ids)].copy()
    if work.empty:
        return work

    if "period" not in work.columns:
        work["period"] = ""

    periods = work["period"].astype(object).tolist()
    keys = [_vci._period_key(period) for period in periods]

    work["_period_year"] = [key[0] for key in keys]
    work["_period_quarter"] = [key[1] for key in keys]

    return work.sort_values(
        ["_period_year", "_period_quarter"],
        ascending=[False, False],
    )


_vci._long_rows = _fixed_long_rows

# Keep original normalized fetcher before replacing the module-level function
# used internally by _vci.run().
_base_fetch_one = _vci.fetch_one


# ---------------------------------------------------------------------------
# Production fetch wrapper / observability
# ---------------------------------------------------------------------------

def fetch_one(symbol: str, asset_type: str | None = None) -> dict | None:
    result = _base_fetch_one(symbol, asset_type)

    if not isinstance(result, dict):
        return result

    # Defensive: legacy poison must never be emitted by the VCI production path.
    if result.get("non_stock"):
        return None

    result["schema_version"] = 9

    status = result.setdefault("data_status", {})
    ratio = result.get("ratio") or {}
    income = result.get("income") or {}
    balance = result.get("balance") or {}
    cashflow = result.get("cashflow") or {}

    status["statement_source"] = (
        "vci_long_3.2.8"
        if status.get("statement_source")
        else None
    )
    status["ratio_period"] = result.get("period") or None
    status["revenue_available"] = income.get("revenue") is not None
    status["equity_available"] = balance.get("equity") is not None
    status["cf_available"] = cashflow.get("cf_operating") is not None
    status["growth_available"] = (
        income.get("rev_growth_qoq") is not None
        or income.get("profit_growth_qoq") is not None
    )

    required = {
        "ratio": status.get("ratio_source") is not None,
        "net_profit": income.get("net_profit") is not None,
        "total_assets": balance.get("total_assets") is not None,
        "cfo": status["cf_available"],
    }
    status["missing_fields"] = [
        field
        for field, available in required.items()
        if not available
    ]
    status["incomplete"] = bool(status["missing_fields"])

    # Keep the exact existing finance_score math/contract.
    result["finance_score"] = _vci._compute_finance_score(result)

    return result


# Make the validated wrapper the function used by _vci.run().
_vci.fetch_one = fetch_one


# ---------------------------------------------------------------------------
# Re-export production API expected by cron + intraday lazy fetch
# ---------------------------------------------------------------------------

def load_cache() -> dict:
    return _vci.load_cache()


def save_cache(symbols_dict: dict) -> None:
    _vci.save_cache(symbols_dict)


def get_scan_universe(industry_map: list) -> list[str]:
    return _vci.get_scan_universe(industry_map)


def run(extra_symbols: list[str] | None = None) -> dict:
    return _vci.run(extra_symbols=extra_symbols)


SCHEMA_VERSION = 9
CACHE_FILE = "finance/cache.json"
SOURCE = "VCI"
MAX_WORKERS = 2


if __name__ == "__main__":
    run()
