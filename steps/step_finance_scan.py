"""
step_finance_scan.py — Daily finance cache builder
===================================================
Chạy trong cron_daily.yml sau step3_context.py.

Mục đích:
  - Fetch báo cáo tài chính KBS cho top ~150 symbols từ industry_map
  - TTL-based: chỉ fetch khi stale, tránh 80 KBS calls/intraday run
  - Concurrent: ThreadPoolExecutor để giảm thời gian
  - Output: output/finance/cache.json — intraday đọc trực tiếp, 0 API calls

TTL strategy:
  - Earnings season (tháng 4,5,7,8,10,11,1,2): TTL = 3 ngày
  - Ngoài earnings season: TTL = 30 ngày
  - Symbol xuất hiện trong top 20 nhưng không có trong cache: fetch ngay (lazy fallback)

CHANGELOG:
  v3 (2026-05-25) — FIX BUG `finance_score` KeyError:
    - fetch_one() giờ gọi _compute_finance_score(result) trước khi return
    - Counter trong run() tách try/except để không double-count
    - Bump SCHEMA_VERSION 2→3

  v4 (2026-05-25) — FIX BUG negative PE/PB bonus:
    - PE < 0 (thua lỗ) trước đây vẫn được "+10đ very cheap" → SAI
    - Fix: PE > 0 mới áp dụng thang bonus, PE < 0 → -5đ (loss penalty)
    - Tương tự PB: PB < 0 = vốn chủ âm → -5đ
    - Bump SCHEMA_VERSION 3→4

  v5 (2026-05-26) — FIX BUG Cash Flow 100% None (KBS quarter limit=1 broken):
    Root cause confirmed qua diagnostic:
      KBS cash_flow(period="quarter", limit=1) trả DataFrame
      chỉ 2 cols ['item', 'item_id'] — THIẾU period column → no data values.

    Fix Option E:
      1. Đổi CF call: period="quarter" → period="year", limit=1
         (year format work bình thường: 50r × 3c với period col '2025')
      2. Thêm 1 KBS call: income_statement(period="year", limit=1)
         → lấy net_profit_year để compute cf_quality đúng period
         (tránh false +5 do mismatch annual_CFO/quarterly_NP ≈ 4x)
      3. Giữ nguyên quarter IS calls cho rev_growth_qoq, profit_growth_qoq
         (Growth group vẫn dùng QoQ như cũ)

    Trade-off:
      - CF data giờ là annual 2025 thay vì Q1 2026
        → Direction (cfo>0 hay <0) vẫn meaningful, thực ra ổn định hơn quarter
        → cf_quality đúng vì NP cũng dùng annual (cùng period)
      - +1 KBS call/symbol = +150 calls/daily run
        (Silver limit 300/min, không vấn đề)

    Bump SCHEMA_VERSION 4→5

  v6 (2026-05-26) — FIX BUG #8 Securities brokers CF schema:
    Diagnostic confirm 5/5 securities brokers (VND, VIX, VFS, SSI, HCM)
    dùng schema khác — operating CF nằm ở key
    `net_cash_flows_from_securities_trading_activities` thay vì
    `operating_cash_flow`.

    Fix: thêm key này vào _CFO_KEYS list. _kbs_lookup sẽ thử lần lượt
    các keys, fallback tự nhiên (industrial dùng operating_cash_flow,
    securities dùng key mới).

    Recover thêm ~11% CF coverage (16/143 symbols miss → 0 missed).

    Bump SCHEMA_VERSION 5→6
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import json
import logging
import re as _re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd
from vnstock_data import Finance

from utils.helpers import now_ict, safe_run, to_float
from utils.cache import load_json, save_json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# Config
# =====================================================

MAX_SYMBOLS     = 150
MAX_WORKERS     = 4
API_CALL_DELAY  = 0.25
EARNINGS_MONTHS = {1, 2, 4, 5, 7, 8, 10, 11}
TTL_EARNINGS    = 3
TTL_NORMAL      = 30

CACHE_FILE = "finance/cache.json"

# Schema version — bump khi đổi structure/fields trong cache entry
# Lịch sử:
#   1 = initial
#   2 = CF đọc từ cash_flow() thay vì balance_sheet()
#   3 = fetch_one precompute finance_score
#   4 = fix negative PE/PB scoring
#   5 = CF year + IS year for cf_quality (KBS quarter broken)
#   6 = securities brokers CF key added (Bug #8)
SCHEMA_VERSION = 6

_NON_STOCK_PATTERN = _re.compile(
    r'^(VN30F|VNINDEX|HNXINDEX|HNX30|VHNDEX|E1|FUED|FUEV|SSIAM|DCDS)', _re.IGNORECASE
)

_STOCK_TYPES = {"stock", "s", "equity", "STOCK", "S", "EQUITY"}


def _is_valid_stock(symbol: str, asset_type: str | None = None) -> bool:
    if not symbol or len(symbol) < 2 or len(symbol) > 5:
        return False
    if _NON_STOCK_PATTERN.match(symbol):
        return False
    if symbol.startswith("X"):
        return False
    if _re.search(r"[0-9]{3,}", symbol):
        return False
    if asset_type is not None:
        return str(asset_type).lower() in {"stock", "s", "equity"}
    return True


# =====================================================
# TTL helpers
# =====================================================

def _current_ttl_days() -> int:
    month = now_ict().month
    return TTL_EARNINGS if month in EARNINGS_MONTHS else TTL_NORMAL


def _is_stale(entry: dict) -> bool:
    """True nếu entry cần re-fetch."""
    if not entry:
        return True
    fetched_at = entry.get("fetched_at")
    if not fetched_at:
        return True

    entry_version = entry.get("schema_version", 0)
    if entry_version < SCHEMA_VERSION:
        return True

    if entry.get("non_stock"):
        try:
            dt = datetime.fromisoformat(fetched_at)
            age_days = (now_ict() - dt).total_seconds() / 86400
            return age_days > 90
        except Exception:
            return True

    if "finance_score" not in entry:
        return True

    ratio = entry.get("ratio", {})
    cf    = entry.get("cashflow", {})
    if ratio.get("pe") is not None and cf.get("cf_operating") is None:
        return True

    try:
        dt = datetime.fromisoformat(fetched_at)
        age_days = (now_ict() - dt).total_seconds() / 86400
        return age_days > _current_ttl_days()
    except Exception:
        return True


# =====================================================
# KBS helpers
# =====================================================

def _dedupe_period_cols(df: pd.DataFrame) -> pd.DataFrame:
    cols = list(df.columns)
    seen: dict = {}
    new_cols = []
    for c in cols:
        if c in ("item", "item_id"):
            new_cols.append(c)
            continue
        if c in seen:
            seen[c] += 1
            new_cols.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            new_cols.append(c)
    df.columns = new_cols
    return df


def _kbs_lookup(df: pd.DataFrame, keys: list, col: str | None = None) -> float | None:
    if df is None or df.empty:
        return None
    df = _dedupe_period_cols(df.copy())
    period_cols = [c for c in df.columns if c not in ("item", "item_id")]
    if not period_cols:
        return None
    target_col = col if col else period_cols[-1]
    idx_col    = "item_id" if "item_id" in df.columns else df.columns[0]
    try:
        df_idx = df.set_index(idx_col)[target_col]
    except Exception:
        return None
    if isinstance(df_idx, pd.DataFrame):
        df_idx = df_idx.iloc[:, 0]
    for k in keys:
        if k in df_idx.index:
            val = to_float(df_idx[k])
            if val is not None:
                return val
    return None


def _kbs_growth(df: pd.DataFrame, keys: list) -> float | None:
    if df is None or df.empty:
        return None
    period_cols = [c for c in df.columns if c not in ["item", "item_id"]]
    if len(period_cols) < 2:
        return None
    v_latest = _kbs_lookup(df, keys, period_cols[-1])
    v_prev   = _kbs_lookup(df, keys, period_cols[-2])
    if v_latest is None or v_prev is None or v_prev == 0:
        return None
    return round((v_latest - v_prev) / abs(v_prev), 4)


def _kbs_yoy_growth(df: pd.DataFrame, keys: list) -> float | None:
    if df is None or df.empty:
        return None
    period_cols = [c for c in df.columns if c not in ["item", "item_id"]]
    if len(period_cols) < 5:
        return None
    v_latest  = _kbs_lookup(df, keys, period_cols[-1])
    v_year_ago = _kbs_lookup(df, keys, period_cols[-5])
    if v_latest is None or v_year_ago is None or v_year_ago == 0:
        return None
    return round((v_latest - v_year_ago) / abs(v_year_ago), 4)


# =====================================================
# Item ID key lists (constants — reuse across calls)
# =====================================================

_NET_PROFIT_KEYS = [
    "profit_after_tax_for_shareholders_of_parent_company",
    "profit_after_tax_for_shareholders_of_the_parent_company",
    "18_net_profit_after_tax",
    "net_profit",
]

_REVENUE_KEYS = ["3_net_revenue", "net_revenue", "revenue"]

_CFO_KEYS = [
    "operating_cash_flow",
    "net_cash_flows_from_operating_activities",
    "i_cash_flows_from_operating_activities",
    # Securities brokers (VND/VIX/VFS/SSI/HCM/...): KBS dùng schema khác
    # Operating CF nằm ở key này thay vì "operating_cash_flow".
    # Diagnostic confirmed 5/5 brokers có row 72 với key này.
    "net_cash_flows_from_securities_trading_activities",
]
_CFI_KEYS = [
    "investing_cash_flow",
    "net_cash_flows_from_investing_activities",
    "ii_cash_flows_from_investing_activities",
]
_CFF_KEYS = [
    "financing_cash_flow",
    "net_cash_flows_from_financing_activities",
    "iii_cash_flows_from_financing_activities",
]


# =====================================================
# Compute finance scores (no change in scoring logic)
# =====================================================

def _compute_finance_score(data: dict) -> dict:
    s = {}

    # ── Fundamental (max ±18đ) ──
    r = data.get("ratio", {}) or {}
    pe  = r.get("pe")
    pb  = r.get("pb")
    roe = r.get("roe")

    fund = 0
    if pe is not None and pe > 0:
        if pe < 10:    fund += 10
        elif pe < 15:  fund += 7
        elif pe <= 25: fund += 3
        else:          fund -= 5
    elif pe is not None and pe < 0:
        fund -= 5

    if pb is not None and pb > 0:
        if pb < 1:     fund += 5
        elif pb <= 2:  fund += 3
        elif pb <= 3:  fund += 0
        else:          fund -= 3
    elif pb is not None and pb < 0:
        fund -= 5

    if roe is not None:
        if roe > 20:   fund += 5
        elif roe > 15: fund += 3
        elif roe > 10: fund += 0
        elif roe < 5:  fund -= 3

    s["fundamental"] = max(-18, min(18, fund))

    # ── Cash Flow (max ±10đ) ──
    c   = data.get("cashflow", {}) or {}
    cfo = c.get("cf_operating")
    cfq = c.get("cf_quality")

    cf = 0
    if cfo is not None:
        cf += 5 if cfo > 0 else -10
    if cfq is not None:
        if cfq > 1:     cf += 5
        elif cfq < 0.5: cf -= 5
    s["cashflow"] = max(-10, min(10, cf))

    # ── Growth (max ±10đ) ──
    i      = data.get("income", {}) or {}
    rev_g  = i.get("rev_growth_qoq")
    np_g   = i.get("profit_growth_qoq")

    growth = 0
    if rev_g is not None:
        if rev_g > 0.20:    growth += 5
        elif rev_g > 0.10:  growth += 3
        elif rev_g > 0:     growth += 1
        elif rev_g < -0.10: growth -= 3
        else:               growth -= 1
    if np_g is not None:
        if np_g > 0.20:    growth += 5
        elif np_g > 0.10:  growth += 3
        elif np_g > 0:     growth += 1
        elif np_g < -0.10: growth -= 3
        else:              growth -= 1
    s["growth"] = max(-10, min(10, growth))

    s["total"] = s["fundamental"] + s["cashflow"] + s["growth"]
    s["max"]   = 38
    return s


# =====================================================
# Fetch finance for one symbol
# =====================================================

def fetch_one(symbol: str, asset_type: str | None = None) -> dict | None:
    """
    Fetch ratio + income(quarter) + balance_sheet + cash_flow(year) + income(year)

    v5 changes:
      - CF: period="year" (KBS quarter broken)
      - +1 call: income_statement(period="year") để compute cf_quality
        đúng period
    """
    if not _is_valid_stock(symbol, asset_type):
        return None

    result = {
        "symbol"        : symbol,
        "fetched_at"    : now_ict().isoformat(),
        "schema_version": SCHEMA_VERSION,
        "ratio"         : {},
        "income"        : {},
        "balance"       : {},
        "cashflow"      : {},
    }

    # ── CALL 1: RATIO (quarter) ──
    df_ratio = None
    try:
        df_ratio = Finance(source="KBS", symbol=symbol).ratio(period="quarter", limit=1)
        log.info(f"  ✅ ratio {symbol}")
    except ValueError as e:
        log.warning(f"  [{symbol}] invalid: {e}")
        return None
    except Exception as e:
        log.warning(f"  ⚠️ ratio {symbol}: {e}")
    time.sleep(API_CALL_DELAY)

    if df_ratio is not None and not df_ratio.empty:
        period_cols      = [c for c in df_ratio.columns if c not in ("item", "item_id")]
        result["period"] = period_cols[-1] if period_cols else ""
        r = result["ratio"]
        r["pe"]           = _kbs_lookup(df_ratio, ["pe_ratio"])
        r["pb"]           = _kbs_lookup(df_ratio, ["pb_ratio"])
        r["roe"]          = _kbs_lookup(df_ratio, ["roe", "roe_trailling"])
        r["roa"]          = _kbs_lookup(df_ratio, ["roa_trailling", "roa"])
        r["eps"]          = _kbs_lookup(df_ratio, ["trailing_eps", "eps"])
        r["bvps"]         = _kbs_lookup(df_ratio, ["book_value_per_share_bvps", "bvps"])
        r["beta"]         = _kbs_lookup(df_ratio, ["beta"])
        r["div_yield"]    = _kbs_lookup(df_ratio, ["dividend_yield"])
        r["gross_margin"] = _kbs_lookup(df_ratio, ["gross_margin"])
        r["net_margin"]   = _kbs_lookup(df_ratio, ["net_margin"])
        r["quick_ratio"]  = _kbs_lookup(df_ratio, ["quick_ratio"])
        r["interest_cov"] = _kbs_lookup(df_ratio, ["interest_coverage"])
        r["ev_ebitda"]    = _kbs_lookup(df_ratio, ["ev_ebitda"])

    # ── CALL 2: INCOME STATEMENT QUARTER (for growth QoQ) ──
    df_is = None
    try:
        df_is = Finance(source="KBS", symbol=symbol).income_statement(
            period="quarter", limit=4)
        log.info(f"  ✅ income_q {symbol}")
    except ValueError:
        return None
    except Exception as e:
        log.warning(f"  ⚠️ income_q {symbol}: {e}")
    time.sleep(API_CALL_DELAY)

    if df_is is not None and not df_is.empty:
        i = result["income"]
        i["revenue"]          = _kbs_lookup(df_is, _REVENUE_KEYS)
        i["gross_profit"]     = _kbs_lookup(df_is, ["5_gross_profit", "gross_profit"])
        i["net_profit"]       = _kbs_lookup(df_is, _NET_PROFIT_KEYS)
        i["operating_profit"] = _kbs_lookup(df_is, ["11_operating_profit", "operating_profit"])
        i["eps"]              = _kbs_lookup(df_is, ["19_earnings_per_share_vnd", "earnings_per_share"])
        i["rev_growth_qoq"]    = _kbs_growth(df_is, _REVENUE_KEYS)
        i["profit_growth_qoq"] = _kbs_growth(df_is, _NET_PROFIT_KEYS)
        i["rev_growth_yoy"]    = _kbs_yoy_growth(df_is, _REVENUE_KEYS)
        i["profit_growth_yoy"] = _kbs_yoy_growth(df_is, _NET_PROFIT_KEYS)

    # ── CALL 3: BALANCE SHEET (quarter) ──
    df_bs = None
    try:
        df_bs = Finance(source="KBS", symbol=symbol).balance_sheet(period="quarter", limit=1)
        log.info(f"  ✅ balance_sheet {symbol}")
    except ValueError:
        return None
    except Exception as e:
        log.warning(f"  ⚠️ balance_sheet {symbol}: {e}")
    time.sleep(API_CALL_DELAY)

    if df_bs is not None and not df_bs.empty:
        b = result["balance"]
        short_assets = _kbs_lookup(df_bs, ["a_short_term_assets"])
        long_assets  = _kbs_lookup(df_bs, ["b_long_term_assets"])
        if short_assets is not None and long_assets is not None:
            b["total_assets"] = round(short_assets + long_assets, 2)
        else:
            b["total_assets"] = _kbs_lookup(df_bs, ["total_assets"])
        b["equity"]     = _kbs_lookup(df_bs,
            ["owner_s_equity", "d_owner_s_equity", "total_equity", "equity"])
        b["total_liab"] = _kbs_lookup(df_bs,
            ["c_liabilities", "total_liabilities", "i_short_term_liabilities"])
        b["short_debt"] = _kbs_lookup(df_bs,
            ["11_short_term_borrowings_and_financial_leases", "short_term_borrowings"])
        b["long_debt"]  = _kbs_lookup(df_bs,
            ["9_long_term_borrowings_and_financial_leases", "long_term_borrowings"])
        if b.get("total_assets") and b.get("equity") and b["equity"] != 0:
            b["debt_to_equity"] = round((b["total_assets"] - b["equity"]) / b["equity"], 3)

    # ── CALL 4: CASH FLOW YEAR ──
    # v5 FIX: period="year" thay vì "quarter"
    # Lý do: KBS cash_flow(period="quarter", limit=1) trả về DataFrame
    # CHỈ 2 cols [item, item_id] — thiếu period column → no data values.
    # Year format work bình thường: 50r × 3c với period col '2025'.
    df_cf = None
    try:
        df_cf = Finance(source="KBS", symbol=symbol).cash_flow(period="year", limit=1)
        log.info(f"  ✅ cash_flow_y {symbol}")
    except ValueError:
        return None
    except Exception as e:
        log.warning(f"  ⚠️ cash_flow_y {symbol}: {e}")
    time.sleep(API_CALL_DELAY)

    if df_cf is not None and not df_cf.empty:
        c = result["cashflow"]
        c["cf_operating"] = _kbs_lookup(df_cf, _CFO_KEYS)
        c["cf_investing"] = _kbs_lookup(df_cf, _CFI_KEYS)
        c["cf_financing"] = _kbs_lookup(df_cf, _CFF_KEYS)

        # Mark this is annual CF, not quarterly
        c["cf_period"] = "annual"

        if c.get("cf_operating") and c.get("cf_investing"):
            c["cf_free"] = round(c["cf_operating"] + c["cf_investing"], 2)

        log.info(f"  CF {symbol}: op={c.get('cf_operating')} "
                 f"inv={c.get('cf_investing')} fin={c.get('cf_financing')}")

    # ── CALL 5: INCOME STATEMENT YEAR (cho cf_quality đúng period) ──
    # v5 NEW: fetch annual net_profit để compute cf_quality = cfo_y / np_y
    # Trước đây dùng net_profit quarter → ratio sai khoảng 4x (false positives).
    df_is_y = None
    try:
        df_is_y = Finance(source="KBS", symbol=symbol).income_statement(
            period="year", limit=1)
        log.info(f"  ✅ income_y {symbol}")
    except ValueError:
        # IS year fail không kill cả symbol — chỉ skip cf_quality
        pass
    except Exception as e:
        log.warning(f"  ⚠️ income_y {symbol}: {e}")
    time.sleep(API_CALL_DELAY)

    net_profit_year = None
    if df_is_y is not None and not df_is_y.empty:
        net_profit_year = _kbs_lookup(df_is_y, _NET_PROFIT_KEYS)
        # Store annual NP for transparency / debugging
        result["income"]["net_profit_year"] = net_profit_year

    # Compute cf_quality with SAME period (annual / annual)
    cfo = result["cashflow"].get("cf_operating")
    if cfo and net_profit_year and net_profit_year != 0:
        result["cashflow"]["cf_quality"] = round(cfo / net_profit_year, 2)
        result["cashflow"]["cf_quality_period"] = "annual"
        log.info(f"  CF quality {symbol}: cfo_y/np_y "
                 f"= {cfo:,.0f}/{net_profit_year:,.0f} "
                 f"= {result['cashflow']['cf_quality']}")
    elif cfo and not net_profit_year:
        log.debug(f"  {symbol}: cf_quality skipped (no annual NP)")

    # ── has_data check ──
    has_data = any([
        result["ratio"].get("pe"),
        result["ratio"].get("roe"),
        result["income"].get("revenue"),
        result["income"].get("net_profit"),
        result["balance"].get("total_assets"),
        result["cashflow"].get("cf_operating"),
    ])
    if not has_data:
        log.warning(f"  [{symbol}] no finance data — marking as non-stock")
        return {
            "symbol"        : symbol,
            "non_stock"     : True,
            "fetched_at"    : now_ict().isoformat(),
            "schema_version": SCHEMA_VERSION,
        }

    # Precompute finance_score
    result["finance_score"] = _compute_finance_score(result)
    return result


# =====================================================
# Load / save cache
# =====================================================

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
    save_json(CACHE_FILE, {
        "generated_at"  : now_ict().isoformat(),
        "schema_version": SCHEMA_VERSION,
        "ttl_days"      : _current_ttl_days(),
        "count"         : len(symbols_dict),
        "symbols"       : symbols_dict,
    })


# =====================================================
# Main scan logic
# =====================================================

_VALID_EXCHANGES = {"HSX", "HOSE", "HNX", "HSX (HOSE)"}


def get_scan_universe(industry_map: list) -> list[str]:
    seen     = set()
    symbols  = []
    skip_ex  = 0
    skip_type = 0

    for row in industry_map:
        sym = row.get("symbol") or row.get("ticker") or row.get("code")
        if not sym:
            continue
        exchange = (row.get("exchange") or "").upper().strip()
        if exchange and exchange not in _VALID_EXCHANGES:
            skip_ex += 1
            continue
        asset_type = row.get("type") or row.get("asset_type")
        if not _is_valid_stock(sym, asset_type):
            skip_type += 1
            continue
        if sym not in seen:
            seen.add(sym)
            symbols.append(sym)
        if len(symbols) >= MAX_SYMBOLS:
            break

    log.info(f"  Skipped: {skip_ex} UPCOM, {skip_type} non-stock (warrant/ETF)")
    return symbols


def run(extra_symbols: list[str] | None = None) -> dict:
    log.info("=== step_finance_scan: START ===")
    log.info(f"TTL mode: {'EARNINGS SEASON' if now_ict().month in EARNINGS_MONTHS else 'NORMAL'} "
             f"({_current_ttl_days()} days)")
    log.info(f"Schema version: {SCHEMA_VERSION}")

    industry_map = load_json("industry_map.json") or []
    if not industry_map:
        log.error("industry_map.json not found — chạy step3_context.py trước")
        return {}

    universe = get_scan_universe(industry_map)

    if extra_symbols:
        for s in extra_symbols:
            if s not in universe:
                universe.append(s)
                log.info(f"  Added extra symbol: {s}")

    log.info(f"Universe: {len(universe)} symbols")

    cache = load_cache()

    to_fetch = []
    to_skip  = []
    for sym in universe:
        entry = cache.get(sym)
        if _is_stale(entry):
            to_fetch.append(sym)
        else:
            to_skip.append(sym)

    log.info(f"Fetch: {len(to_fetch)}, Skip (cache hit): {len(to_skip)}")

    if not to_fetch:
        log.info("All symbols are fresh — nothing to fetch")
        return cache

    fetched_ok        = 0
    fetched_non_stock = 0
    fetched_err       = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(fetch_one, sym): sym for sym in to_fetch}
        for future in as_completed(future_map):
            sym = future_map[future]

            try:
                result = future.result()
            except Exception as e:
                fetched_err += 1
                log.error(f"  ❌ {sym} (fetch error): {e}")
                continue

            if not result:
                fetched_err += 1
                log.warning(f"  ⚠️ {sym}: fetch returned None")
                continue

            if result.get("non_stock"):
                cache[sym] = result
                fetched_non_stock += 1
                log.info(f"  ⏭️  {sym}: non-stock — cached 90d")
                continue

            cache[sym] = result
            fetched_ok += 1
            try:
                fs  = result.get("finance_score") or {}
                pe  = result.get("ratio",    {}).get("pe")
                roe = result.get("ratio",    {}).get("roe")
                cfo = result.get("cashflow", {}).get("cf_operating")
                cfq = result.get("cashflow", {}).get("cf_quality")
                log.info(
                    f"  ✅ {sym} "
                    f"PE={pe} ROE={roe} CFO={cfo} CFq={cfq} "
                    f"score={fs.get('total', 'n/a')} "
                    f"(F={fs.get('fundamental', 'n/a')} "
                    f"CF={fs.get('cashflow', 'n/a')} "
                    f"G={fs.get('growth', 'n/a')})"
                )
            except Exception as e:
                log.warning(f"  ⚠️ {sym}: log format error (data đã cache): {e}")

    save_cache(cache)

    log.info(
        f"Done: {fetched_ok} ok, {fetched_non_stock} non-stock, "
        f"{fetched_err} failed, {len(to_skip)} from cache. "
        f"Total in cache: {len(cache)} symbols"
    )
    log.info("=== step_finance_scan: DONE ===")
    return cache


if __name__ == "__main__":
    run()
