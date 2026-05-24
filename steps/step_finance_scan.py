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

MAX_SYMBOLS     = 150       # top N từ industry_map
MAX_WORKERS     = 4         # concurrent KBS calls — giảm để tránh rate limit
API_CALL_DELAY  = 0.25      # giây giữa các API calls (4 calls/sec = 240/min < 300 Silver)
EARNINGS_MONTHS = {1, 2, 4, 5, 7, 8, 10, 11}  # mùa BCTC
TTL_EARNINGS    = 3         # ngày
TTL_NORMAL      = 30        # ngày

CACHE_FILE = "finance/cache.json"

# Pattern của non-stock symbols cần bỏ qua
# ETF: E1VFVN30, FUEVFVND...  Derivatives: VN30F2401...  Index: VNINDEX, HNXINDEX
import re as _re
_NON_STOCK_PATTERN = _re.compile(
    r'^(VN30F|VNINDEX|HNXINDEX|HNX30|VHNDEX|E1|FUED|FUEV|SSIAM|DCDS)', _re.IGNORECASE
)

def _is_valid_stock(symbol: str) -> bool:
    """
    Bỏ qua non-stock symbols — KBS chỉ hỗ trợ cổ phiếu thường.

    Loại bỏ:
    - ETF/Index: VN30F*, VNINDEX, E1*, FUEV*, SSIAM*
    - Chứng quyền (covered warrants): X* (VD: XMD, XLV, X77, X26)
      → KBS throws ValueError: Mã CK không hợp lệ
    - Chứng quyền dạng khác: C + mã gốc + số (VD: CVPB2101)
    - Derivatives với số dài: VN30F2401
    """
    if not symbol or len(symbol) < 2 or len(symbol) > 5:
        return False
    if _NON_STOCK_PATTERN.match(symbol):
        return False
    # Chứng quyền: bắt đầu bằng X (VD: XMD, XLV, X77, X26, XPH, XMP...)
    if symbol.startswith('X') and len(symbol) <= 5:
        return False
    # Derivatives/warrants với số dài
    if _re.search(r'[0-9]{3,}', symbol):
        return False
    return True

# =====================================================
# TTL helpers
# =====================================================

def _current_ttl_days() -> int:
    month = now_ict().month
    return TTL_EARNINGS if month in EARNINGS_MONTHS else TTL_NORMAL

def _is_stale(entry: dict) -> bool:
    """True nếu entry chưa có hoặc đã quá TTL."""
    if not entry:
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

# =====================================================
# KBS helpers — same pattern as step_all.py
# =====================================================

def _dedupe_period_cols(df: pd.DataFrame) -> pd.DataFrame:
    """KBS đôi khi trả về duplicate column names (vd: 2025-Q4 × 4).
    Rename để đảm bảo unique: 2025-Q4, 2025-Q4_1, 2025-Q4_2..."""
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
            return to_float(df_idx[k])
    return None

def _kbs_growth(df: pd.DataFrame, keys: list) -> float | None:
    """QoQ growth từ limit=4 data."""
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
    """YoY growth: kỳ[-1] vs kỳ[-5] nếu có đủ 5 kỳ (limit=8)."""
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
# Fetch finance for one symbol
# =====================================================

def fetch_one(symbol: str) -> dict | None:
    """
    Fetch ratio + income + balance từ KBS với rate limiting.
    Silver tier: 300 req/min → throttle với API_CALL_DELAY giữa mỗi call.
    ValueError (non-stock symbol) → trả về None ngay, không retry.
    """
    import time

    if not _is_valid_stock(symbol):
        log.debug(f"  [{symbol}] skipped — non-stock pattern")
        return None

    result = {
        "symbol"    : symbol,
        "fetched_at": now_ict().isoformat(),
        "ratio"     : {},
        "income"    : {},
        "balance"   : {},
        "cashflow"  : {},
    }

    # RATIO
    try:
        df_ratio = Finance(source="KBS", symbol=symbol).ratio(
            period="quarter", limit=1)
        log.info(f"  ✅ ratio {symbol}")
    except ValueError as e:
        log.warning(f"  [{symbol}] invalid stock: {e}")
        return None
    except Exception as e:
        log.warning(f"  ⚠️ ratio {symbol}: {e}")
        df_ratio = None
    time.sleep(API_CALL_DELAY)
    if df_ratio is not None and not df_ratio.empty:
        period_cols = [c for c in df_ratio.columns if c not in ["item", "item_id"]]
        result["period"] = period_cols[-1] if period_cols else ""
        r = result["ratio"]
        r["pe"]            = _kbs_lookup(df_ratio, ["pe_ratio"])
        r["pb"]            = _kbs_lookup(df_ratio, ["pb_ratio"])
        r["roe"]           = _kbs_lookup(df_ratio, ["roe", "roe_trailling"])
        r["roa"]           = _kbs_lookup(df_ratio, ["roa_trailling", "roa"])
        r["eps"]           = _kbs_lookup(df_ratio, ["trailing_eps", "eps"])
        r["bvps"]          = _kbs_lookup(df_ratio, ["book_value_per_share_bvps", "bvps"])
        r["beta"]          = _kbs_lookup(df_ratio, ["beta"])
        r["div_yield"]     = _kbs_lookup(df_ratio, ["dividend_yield"])
        r["gross_margin"]  = _kbs_lookup(df_ratio, ["gross_margin"])
        r["net_margin"]    = _kbs_lookup(df_ratio, ["net_margin"])
        r["quick_ratio"]   = _kbs_lookup(df_ratio, ["quick_ratio"])
        r["interest_cov"]  = _kbs_lookup(df_ratio, ["interest_coverage"])
        r["ev_ebitda"]     = _kbs_lookup(df_ratio, ["ev_ebitda"])

    # INCOME STATEMENT — limit=4 cho QoQ growth
    import time
    try:
        df_is = Finance(source="KBS", symbol=symbol).income_statement(
            period="quarter", limit=4)
        log.info(f"  ✅ income {symbol}")
    except ValueError:
        return None
    except Exception as e:
        log.warning(f"  ⚠️ income {symbol}: {e}")
        df_is = None
    time.sleep(API_CALL_DELAY)
    if df_is is not None and not df_is.empty:
        i = result["income"]
        i["revenue"]          = _kbs_lookup(df_is,
            ["3_net_revenue", "net_revenue", "revenue"])
        i["gross_profit"]     = _kbs_lookup(df_is,
            ["5_gross_profit", "gross_profit"])
        i["net_profit"]       = _kbs_lookup(df_is,
            ["profit_after_tax_for_shareholders_of_parent_company", "profit_after_tax_for_shareholders_of_the_parent_company",
             "18_net_profit_after_tax", "net_profit"])
        i["operating_profit"] = _kbs_lookup(df_is,
            ["11_operating_profit", "operating_profit"])
        i["eps"]              = _kbs_lookup(df_is,
            ["19_earnings_per_share_vnd", "earnings_per_share"])
        # Growth
        i["rev_growth_qoq"]    = _kbs_growth(df_is,
            ["3_net_revenue", "net_revenue", "revenue"])
        i["profit_growth_qoq"] = _kbs_growth(df_is,
            ["profit_after_tax_for_shareholders_of_parent_company", "profit_after_tax_for_shareholders_of_the_parent_company",
             "18_net_profit_after_tax", "net_profit"])
        i["rev_growth_yoy"]    = _kbs_yoy_growth(df_is,
            ["3_net_revenue", "net_revenue", "revenue"])
        i["profit_growth_yoy"] = _kbs_yoy_growth(df_is,
            ["profit_after_tax_for_shareholders_of_parent_company", "profit_after_tax_for_shareholders_of_the_parent_company",
             "18_net_profit_after_tax", "net_profit"])

    # BALANCE SHEET
    df_bs = safe_run(f"balance_sheet {symbol}",
             lambda: Finance(source="KBS", symbol=symbol).balance_sheet(
                 period="quarter", limit=1))
    if df_bs is not None and not df_bs.empty:
        b = result["balance"]
        b["total_assets"] = _kbs_lookup(df_bs, ["total_assets"])
        b["equity"]       = _kbs_lookup(df_bs,
            ["owner_s_equity", "d_owner_s_equity",
             "total_owner_s_equity_and_liabilities"])
        b["total_liab"]   = _kbs_lookup(df_bs,
            ["c_liabilities", "i_short_term_liabilities"])
        b["short_debt"]   = _kbs_lookup(df_bs,
            ["11_short_term_borrowings_and_financial_leases",
             "i_short_term_liabilities"])
        b["long_debt"]    = _kbs_lookup(df_bs,
            ["9_long_term_borrowings_and_financial_leases",
             "ii_long_term_liabilities"])
        # Derived
        if b["total_assets"] and b["equity"] and b["total_assets"] != 0:
            b["debt_to_equity"] = round(
                (b["total_assets"] - b["equity"]) / b["equity"], 3) \
                if b["equity"] != 0 else None

    # BALANCE SHEET + CASH FLOW
    # KBS trộn CF items vào balance_sheet() DataFrame
    import time
    try:
        df_bs = Finance(source="KBS", symbol=symbol).balance_sheet(
            period="quarter", limit=1)
        log.info(f"  ✅ balance_sheet {symbol}")
    except ValueError:
        return None
    except Exception as e:
        log.warning(f"  ⚠️ balance_sheet {symbol}: {e}")
        df_bs = None
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
            b["debt_to_equity"] = round(
                (b["total_assets"] - b["equity"]) / b["equity"], 3)

        # CF — đọc từ df_bs (KBS design: CF items mixed into balance_sheet)
        c = result["cashflow"]
        c["cf_operating"] = _kbs_lookup(df_bs,
            ["i_cash_flows_from_operating_activities",
             "operating_cash_flow",
             "net_cash_flows_from_operating_activities"])
        c["cf_investing"]  = _kbs_lookup(df_bs,
            ["investing_cash_flow",
             "ii_cash_flows_from_investing_activities",
             "net_cash_flows_from_investing_activities"])
        c["cf_financing"]  = _kbs_lookup(df_bs,
            ["financing_cash_flow",
             "iii_cash_flows_from_financing_activities",
             "net_cash_flows_from_financing_activities"])

        # CF quality + free CF
        net_profit = result["income"].get("net_profit")
        if c.get("cf_operating") and net_profit and net_profit != 0:
            c["cf_quality"] = round(c["cf_operating"] / net_profit, 2)
        if c.get("cf_operating") and c.get("cf_investing"):
            c["cf_free"] = round(c["cf_operating"] + c["cf_investing"], 2)

    # Precompute finance_scores — scoring dùng luôn, không tính lại
    result["finance_score"] = _compute_finance_score(result)

    # Kiểm tra có data không
    has_data = any([
        result["ratio"].get("pe"),
        result["income"].get("revenue"),
        result["balance"].get("total_assets"),
    ])
    if not has_data:
        log.warning(f"  [{symbol}] no finance data fetched")
        return None

    return result

# =====================================================
# Precompute finance scores
# Scoring dùng trực tiếp từ cache, không tính lại intraday
# =====================================================

def _compute_finance_score(data: dict) -> dict:
    """
    Tính điểm fundamental, cashflow, growth.
    Trả về dict với breakdown + total.
    Nhất quán với thresholds trong step_scoring.py.
    """
    s = {}

    # Fundamental (max 18đ) — nhất quán với step_scoring.py
    r = data.get("ratio", {})
    pe  = r.get("pe")
    pb  = r.get("pb")
    roe = r.get("roe")

    fund = 0
    if pe:
        if pe < 10:    fund += 10
        elif pe < 15:  fund += 7
        elif pe <= 25: fund += 3
        else:          fund -= 5
    if pb:
        if pb < 1:     fund += 5
        elif pb <= 2:  fund += 3
        elif pb <= 3:  fund += 0
        else:          fund -= 3
    if roe:
        if roe > 20:   fund += 5
        elif roe > 15: fund += 3
        elif roe > 10: fund += 0
        elif roe < 5:  fund -= 3
    s["fundamental"] = max(-18, min(18, fund))

    # Cash Flow (max 10đ) — nhất quán với step_scoring.py
    c   = data.get("cashflow", {})
    cfo = c.get("cf_operating")
    cfq = c.get("cf_quality")

    cf = 0
    if cfo is not None:
        cf += 5 if cfo > 0 else -10
    if cfq is not None:
        if cfq > 1:   cf += 5
        elif cfq < 0.5: cf -= 5
    s["cashflow"] = max(-10, min(10, cf))

    # Growth (max 10đ) — nhóm MỚI, chưa có trong scoring hiện tại
    # Sẽ được dùng khi step_scoring.py được update ở P3
    i      = data.get("income", {})
    rev_g  = i.get("rev_growth_qoq")
    np_g   = i.get("profit_growth_qoq")

    growth = 0
    if rev_g is not None:
        if rev_g > 0.20:   growth += 5
        elif rev_g > 0.10: growth += 3
        elif rev_g > 0:    growth += 1
        elif rev_g < -0.10: growth -= 3
        else:               growth -= 1
    if np_g is not None:
        if np_g > 0.20:    growth += 5
        elif np_g > 0.10:  growth += 3
        elif np_g > 0:     growth += 1
        elif np_g < -0.10: growth -= 3
        else:               growth -= 1
    s["growth"] = max(-10, min(10, growth))

    s["total"] = s["fundamental"] + s["cashflow"] + s["growth"]
    s["max"]   = 38  # 18 + 10 + 10
    return s

# =====================================================
# Load / save cache
# =====================================================

def load_cache() -> dict:
    """Load cache hiện tại, trả về dict {symbol: entry}."""
    data = load_json(CACHE_FILE)
    if not data:
        return {}
    # Support cả format cũ (flat dict) và mới
    if isinstance(data, dict) and "symbols" in data:
        return data["symbols"]
    if isinstance(data, dict):
        return data
    return {}

def save_cache(symbols_dict: dict) -> None:
    """Lưu cache với metadata."""
    save_json(CACHE_FILE, {
        "generated_at": now_ict().isoformat(),
        "ttl_days"    : _current_ttl_days(),
        "count"       : len(symbols_dict),
        "symbols"     : symbols_dict,
    })

# =====================================================
# Main scan logic
# =====================================================

def get_scan_universe(industry_map: list) -> list[str]:
    """Lấy danh sách symbols cần scan từ industry_map.
    - Robust column name (symbol/ticker/code)
    - Filter non-stock symbols (ETF, derivatives, index)
    """
    seen = set()
    symbols = []
    skipped = 0
    for row in industry_map:
        sym = row.get("symbol") or row.get("ticker") or row.get("code")
        if not sym:
            continue
        if not _is_valid_stock(sym):
            skipped += 1
            continue
        if sym not in seen:
            seen.add(sym)
            symbols.append(sym)
        if len(symbols) >= MAX_SYMBOLS:
            break
    if skipped:
        log.info(f"  Skipped {skipped} non-stock symbols (ETF/derivatives)")
    return symbols

def run(extra_symbols: list[str] | None = None) -> dict:
    """
    Main entry point.
    extra_symbols: symbols cần đảm bảo có trong cache
                   (ví dụ top 20 từ intraday, dùng khi lazy fallback).
    Trả về cache dict đã update.
    """
    log.info("=== step_finance_scan: START ===")
    log.info(f"TTL mode: {'EARNINGS SEASON' if now_ict().month in EARNINGS_MONTHS else 'NORMAL'} "
             f"({_current_ttl_days()} days)")

    industry_map = load_json("industry_map.json") or []
    if not industry_map:
        log.error("industry_map.json not found — chạy step3_context.py trước")
        return {}

    universe = get_scan_universe(industry_map)

    # Đảm bảo extra_symbols nằm trong universe
    if extra_symbols:
        for s in extra_symbols:
            if s not in universe:
                universe.append(s)
                log.info(f"  Added extra symbol: {s}")

    log.info(f"Universe: {len(universe)} symbols")

    cache = load_cache()

    # Xác định symbols cần fetch
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

    # Concurrent fetch
    fetched_ok  = 0
    fetched_err = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(fetch_one, sym): sym for sym in to_fetch}
        for future in as_completed(future_map):
            sym = future_map[future]
            try:
                result = future.result()
                if result:
                    cache[sym] = result
                    fetched_ok += 1
                    log.info(
                        f"  ✅ {sym} "
                        f"PE={result['ratio'].get('pe')} "
                        f"ROE={result['ratio'].get('roe')} "
                        f"CFO={result['cashflow'].get('cf_operating')} "
                        f"score={result['finance_score']['total']}"
                    )
                else:
                    fetched_err += 1
                    log.warning(f"  ⚠️ {sym}: no data")
            except Exception as e:
                fetched_err += 1
                log.error(f"  ❌ {sym}: {e}")

    save_cache(cache)

    log.info(
        f"Done: {fetched_ok} fetched, {fetched_err} failed, "
        f"{len(to_skip)} from cache. "
        f"Total: {len(cache)} symbols"
    )
    log.info("=== step_finance_scan: DONE ===")
    return cache


if __name__ == "__main__":
    run()
