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
  v3 (2026-05-25) — FIX BUG `finance_score` KeyError.
  v4 (2026-05-25) — FIX BUG negative PE/PB bonus.
  v5 (2026-05-26) — FIX BUG Cash Flow 100% None (KBS quarter limit=1 broken).
  v6 (2026-05-26) — FIX BUG #8 Securities brokers CF schema.

  v7 (2026-05-29) — VCI ratio_summary fallback + better empty logging:
    Diagnostic (debug_vci_full.py) confirmed:
      - VCI Finance.* ALL empty universally (even HPG/VCB)
      - Company(VCI).ratio_summary() WORK với mọi mã đã test:
        KDC (40r×61c), CCC (8r×61c), KBS-empty symbols đều có data
      - Cover ~75% ratio fields: pe, pb, roe, roa, dividend_yield,
        gross_margin, after_tax_profit_margin → net_margin,
        quick_ratio, ev_to_ebitda
      - Thiếu: eps, beta, interest_coverage (acceptable)

    Changes:
      1. Sau CALL 1 (KBS ratio) nếu EMPTY → call Company(VCI).ratio_summary
         làm fallback. Track via result["data_status"]["ratio_source"].
      2. KBS empty calls log "⚠️ EMPTY" thay vì "✅" — phân biệt rõ
         "call thành công" vs "có data thật".
      3. Thêm result["data_status"] = {ratio_source, cf_available,
         growth_available, incomplete} — minh bạch data gap.
      4. _is_stale không re-fetch endlessly khi cf_available=False
         (chấp nhận data gap, không spin loop).
      5. VCI ratio_summary trả decimal (0.1274) còn KBS trả percentage
         (12.74) → _vci_pct() normalize cho roe/roa/margins/yield.

    Bump SCHEMA_VERSION 6→7

  v8 (2026-05-30) — Curated universe selection (VN100 + HNX30).
    Diagnostic (debug_index_groups.py) confirmed via Listing.symbols_by_group:
      - "VN100" → 100 HSX large/mid-cap (returns pandas Series)
      - "HNX30" → 30 top HNX
      - "VN30"  → subset of VN100 (không cần thêm)
      - Tên khác (VN-100, VNX100, HNX-30...) → RetryError

    Vấn đề cũ: get_scan_universe lấy 150 mã ĐẦU TIÊN industry_map (Z→A order)
    → toàn penny V→Y, bỏ hết blue-chip A→U (VNM/VCB/VIC/HPG/FPT...).

    Fix (chiến lược B — superset của A):
      Priority order, dedupe, cap MAX_SYMBOLS:
        1. VN100  (100) — curated large/mid HSX
        2. HNX30  (30)  — curated top HNX        → core 130 (= "A", luôn có đủ)
        3. VNSML  fill  — small-cap index (curated) cho ~20 slot còn lại
        4. industry_map — last-resort fill nếu index API fail
        5. industry_map first-150 — ultimate fallback nếu MỌI index empty
      → B ⊇ A: core VN100+HNX30 luôn được add TRƯỚC nên không bao giờ mất.
      → Mọi bước bọc try/except: daily scan không bao giờ chết nếu API đổi.

    Không bump SCHEMA_VERSION (entry schema không đổi, chỉ đổi mã nào được scan).

  v9 (2026-06-21) — FIX BUG div_yield unit mismatch (KBS path).
    Verify (diag_vci_finance + cache audit): KBS ratio trả `dividend_yield` dạng
    DECIMAL (0.03 = 3%), khác roe/margins (KBS trả %). VCI path đã chuẩn hoá qua
    _vci_pct; KBS path KHÔNG → r_div_yield lưu decimal → score_dividend_yield
    (kỳ vọng %, ngưỡng >2/>4/>6) luôn ra 0 cho mọi mã KBS-sourced (328/402) →
    ext_div_score 0/40.
    Fix: bọc _vci_pct cho KBS div_yield (0.03 → 3.0; idempotent nếu đã là %).
    Bump SCHEMA_VERSION 7→8 → force re-fetch để chuẩn hoá 328 entry decimal cũ.

  v10 (2026-06-21) — Silence log spam balance_sheet EMPTY.
    Verify (diag_balance_sheet): 6 mã × 2 source × 4 (period,limit) = 48/48 EMPTY
    → Finance.balance_sheet outage thượng nguồn (cả KBS lẫn VCI). Không fix được
    trong pipeline. score_de đã graceful (dòng 559: if de is not None) → mất
    sub-signal D/E nhưng không lệch điểm.
    Đổi log: bỏ WARNING per-symbol (~150 dòng/daily), thay bằng 1 dòng INFO tổng
    cuối run. Vẫn cố fetch để khi lib khôi phục là có data ngay.

  v11 (2026-08-18) — Protect cache from transient/overload API empties.
    Diagnostic 130 symbols confirmed concurrent/high-load fetch can return EMPTY
    while sequential retry recovers data for the same symbols.
    Fix:
      1. No finance data => fetch failure (None), NEVER infer non_stock.
      2. has_data checks `is not None`, so legitimate zero values count as data.
      3. Purge legacy `non_stock` entries for the authoritative stock universe
         before scanning, forcing poisoned cache entries to be revalidated.
      4. Failed refresh keeps last-known-good cache; a poisoned legacy entry that
         was purged stays absent instead of blocking intraday lazy fetch for 90d.
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
from vnstock_data import Finance, Company, Listing   # v7: +Company  v8: +Listing

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

# v9 (2026-06-21): balance_sheet EMPTY cho 100% mã VN100 (xác nhận diag_balance_sheet:
# 6 mã × 2 source × 4 (period,limit) = 48/48 EMPTY → library/API outage, không phải
# bug pipeline). Spam 150 WARNING/run vô ích. Đổi sang: tăng counter im lặng, in 1
# dòng tổng cuối run. score_de đã graceful (skip nếu de=None) → không ảnh hưởng điểm.
_BALANCE_EMPTY_COUNT = [0]

# Schema version — bump khi đổi structure/fields trong cache entry
# Lịch sử:
#   1 = initial
#   2 = CF từ cash_flow() thay vì balance_sheet()
#   3 = precompute finance_score
#   4 = fix negative PE/PB scoring
#   5 = CF year + IS year for cf_quality
#   6 = securities brokers CF key added
#   7 = VCI ratio_summary fallback + data_status flag
SCHEMA_VERSION = 8

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

    # v11: old `non_stock` entries may have been poisoned by transient API EMPTY.
    # The scan universe itself is already stock-only, so never let this flag
    # suppress a re-fetch for a current universe member.
    if entry.get("non_stock"):
        return True

    if "finance_score" not in entry:
        return True

    # v7 CHANGE: chỉ re-fetch khi MIGHT có CF (cf_available chưa được
    # đánh dấu False bởi run trước). Tránh spin loop với mã KBS không có CF.
    ratio  = entry.get("ratio", {})
    cf     = entry.get("cashflow", {})
    status = entry.get("data_status", {})
    cf_was_available = status.get("cf_available", True)  # default True for back-compat
    if (ratio.get("pe") is not None
            and cf.get("cf_operating") is None
            and cf_was_available):
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
    v_latest   = _kbs_lookup(df, keys, period_cols[-1])
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
    # Securities brokers schema (v6)
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
# v7 NEW — VCI ratio_summary fallback helpers
# =====================================================

def _vci_pct(v) -> float | None:
    """
    VCI ratio_summary trả ratios dạng decimal (e.g. roe=0.1274).
    KBS trả dạng percentage (e.g. roe=12.74).
    Scoring thresholds (PE/PB không đổi, nhưng roe>10/15/20) expect KBS scale.

    Normalize: nếu |v| < 1 (chắc chắn decimal) → ×100. Còn lại giữ nguyên.
    Edge case: ROE thật < 1% sẽ bị nhầm thành 100×; chấp nhận vì hiếm.
    """
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if pd.isna(v):
        return None
    if v == 0:
        return 0.0
    return v * 100 if abs(v) < 1 else v


def _fetch_vci_ratio_fallback(symbol: str) -> dict | None:
    """
    Fallback khi KBS ratio empty. Dùng Company(VCI).ratio_summary().
    Trả về dict cùng schema với KBS ratio output, hoặc None nếu fail.

    Filter RATIO_TTM (trailing 12 months), lấy period mới nhất.
    """
    try:
        df = Company(source="VCI", symbol=symbol).ratio_summary()
    except Exception as e:
        log.warning(f"  ⚠️ VCI ratio_summary {symbol}: {e}")
        return None

    if df is None or df.empty:
        return None

    # Filter RATIO_TTM nếu có cột ratio_type
    if "ratio_type" in df.columns:
        df_ttm = df[df["ratio_type"] == "RATIO_TTM"]
        if not df_ttm.empty:
            df = df_ttm

    # Sort latest period (year, quarter) descending
    sort_cols = [c for c in ("year", "quarter") if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=False)

    row = df.iloc[0]

    def _get(col):
        if col not in df.columns:
            return None
        v = row[col]
        if pd.isna(v):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    out = {
        "pe"          : _get("pe"),
        "pb"          : _get("pb"),
        "roe"         : _vci_pct(_get("roe")),
        "roa"         : _vci_pct(_get("roa")),
        "eps"         : None,                                # VCI không có
        "bvps"        : None,                                # VCI không có
        "beta"        : None,                                # VCI không có
        "div_yield"   : _vci_pct(_get("dividend_yield")),
        "gross_margin": _vci_pct(_get("gross_margin")),
        "net_margin"  : _vci_pct(_get("after_tax_profit_margin")),
        "quick_ratio" : _get("quick_ratio"),
        "interest_cov": None,                                # VCI không có
        "ev_ebitda"   : _get("ev_to_ebitda"),
    }

    # Có ít nhất 1 field non-null
    if any(v is not None for v in out.values()):
        # Period tag để debug
        period_str = ""
        if "year" in df.columns:
            year = row.get("year", "")
            qtr  = row.get("quarter", "")
            period_str = f"{int(year)}-Q{int(qtr)}" if qtr else str(year)
        return {"ratio": out, "period": period_str}
    return None


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

def _log_df(symbol: str, name: str, df) -> str:
    """v7 helper — log success/empty consistently. Return status string."""
    if df is None:
        log.warning(f"  ⚠️ {name} {symbol}: None")
        return "none"
    if df.empty:
        log.warning(f"  ⚠️ {name} {symbol}: EMPTY")
        return "empty"
    log.info(f"  ✅ {name} {symbol}")
    return "ok"


def fetch_one(symbol: str, asset_type: str | None = None) -> dict | None:
    """
    Fetch KBS ratio + income(q) + balance_sheet + cash_flow(y) + income(y).
    v7: VCI ratio_summary fallback nếu KBS ratio empty.
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
        # v7: data_status tracks what was actually obtained vs missing
        "data_status"   : {
            "ratio_source"    : None,    # "kbs" | "vci_fallback" | None
            "cf_available"    : False,
            "growth_available": False,
            "incomplete"      : True,    # finalized at the end
        },
    }

    # ── CALL 1: RATIO (quarter) — KBS ──
    df_ratio = None
    try:
        df_ratio = Finance(source="KBS", symbol=symbol).ratio(period="quarter", limit=1)
        _log_df(symbol, "ratio_kbs", df_ratio)
    except ValueError as e:
        log.warning(f"  [{symbol}] invalid: {e}")
        return None
    except Exception as e:
        log.warning(f"  ⚠️ ratio_kbs {symbol}: {e}")
    time.sleep(API_CALL_DELAY)

    if df_ratio is not None and not df_ratio.empty:
        # Path A: KBS ratio has data
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
        # v9: KBS trả div_yield DECIMAL (0.03=3%) khác roe/margins (%). Bọc
        # _vci_pct để chuẩn hoá về % cho khớp score_dividend_yield + VCI path.
        r["div_yield"]    = _vci_pct(_kbs_lookup(df_ratio, ["dividend_yield"]))
        r["gross_margin"] = _kbs_lookup(df_ratio, ["gross_margin"])
        r["net_margin"]   = _kbs_lookup(df_ratio, ["net_margin"])
        r["quick_ratio"]  = _kbs_lookup(df_ratio, ["quick_ratio"])
        r["interest_cov"] = _kbs_lookup(df_ratio, ["interest_coverage"])
        r["ev_ebitda"]    = _kbs_lookup(df_ratio, ["ev_ebitda"])
        result["data_status"]["ratio_source"] = "kbs"
    else:
        # Path B: KBS empty → VCI fallback (v7)
        log.info(f"  ↪︎ KBS ratio empty for {symbol} — trying VCI ratio_summary fallback")
        fallback = _fetch_vci_ratio_fallback(symbol)
        time.sleep(API_CALL_DELAY)
        if fallback:
            result["ratio"]  = fallback["ratio"]
            result["period"] = fallback.get("period", "")
            result["data_status"]["ratio_source"] = "vci_fallback"
            log.info(
                f"  ✅ ratio_vci {symbol}: PE={result['ratio'].get('pe')} "
                f"PB={result['ratio'].get('pb')} ROE={result['ratio'].get('roe')}"
            )
        else:
            log.warning(f"  ⚠️ ratio fallback {symbol}: VCI also empty")

    # ── CALL 2: INCOME STATEMENT QUARTER (for growth QoQ) ──
    df_is = None
    try:
        df_is = Finance(source="KBS", symbol=symbol).income_statement(
            period="quarter", limit=4)
        _log_df(symbol, "income_q", df_is)
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
        if i.get("rev_growth_qoq") is not None or i.get("profit_growth_qoq") is not None:
            result["data_status"]["growth_available"] = True

    # ── CALL 3: BALANCE SHEET (quarter) ──
    # v9: lib outage xác nhận → KHÔNG log warning per-symbol (spam). Chỉ đếm,
    # tổng kết cuối run. Vẫn cố fetch để lúc lib khôi phục là có data luôn.
    df_bs = None
    try:
        df_bs = Finance(source="KBS", symbol=symbol).balance_sheet(period="quarter", limit=1)
        if df_bs is None or df_bs.empty:
            _BALANCE_EMPTY_COUNT[0] += 1  # silent — tổng kết ở run()
        else:
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
    df_cf = None
    try:
        df_cf = Finance(source="KBS", symbol=symbol).cash_flow(period="year", limit=1)
        _log_df(symbol, "cash_flow_y", df_cf)
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
        c["cf_period"]    = "annual"

        if c.get("cf_operating") and c.get("cf_investing"):
            c["cf_free"] = round(c["cf_operating"] + c["cf_investing"], 2)

        log.info(f"  CF {symbol}: op={c.get('cf_operating')} "
                 f"inv={c.get('cf_investing')} fin={c.get('cf_financing')}")

        if c.get("cf_operating") is not None:
            result["data_status"]["cf_available"] = True

    # ── CALL 5: INCOME STATEMENT YEAR (cho cf_quality đúng period) ──
    df_is_y = None
    try:
        df_is_y = Finance(source="KBS", symbol=symbol).income_statement(
            period="year", limit=1)
        _log_df(symbol, "income_y", df_is_y)
    except ValueError:
        pass
    except Exception as e:
        log.warning(f"  ⚠️ income_y {symbol}: {e}")
    time.sleep(API_CALL_DELAY)

    net_profit_year = None
    if df_is_y is not None and not df_is_y.empty:
        net_profit_year = _kbs_lookup(df_is_y, _NET_PROFIT_KEYS)
        result["income"]["net_profit_year"] = net_profit_year

    cfo = result["cashflow"].get("cf_operating")
    if cfo and net_profit_year and net_profit_year != 0:
        result["cashflow"]["cf_quality"] = round(cfo / net_profit_year, 2)
        result["cashflow"]["cf_quality_period"] = "annual"
        log.info(f"  CF quality {symbol}: cfo_y/np_y "
                 f"= {cfo:,.0f}/{net_profit_year:,.0f} "
                 f"= {result['cashflow']['cf_quality']}")

    # ── has_data check ──
    has_data = any(v is not None for v in [
        result["ratio"].get("pe"),
        result["ratio"].get("roe"),
        result["income"].get("revenue"),
        result["income"].get("net_profit"),
        result["balance"].get("total_assets"),
        result["cashflow"].get("cf_operating"),
    ])
    if not has_data:
        log.warning(
            f"  [{symbol}] no finance data — treating as fetch failure; "
            "cache will not be overwritten"
        )
        return None

    # v7: finalize incomplete flag
    status = result["data_status"]
    status["incomplete"] = (
        status["ratio_source"] is None
        or not status["cf_available"]
        or not status["growth_available"]
    )

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

# v8: Curated index groups (confirmed working via Listing.symbols_by_group)
#   Core = VN100 + HNX30 (130 mã) — luôn add trước → universe ⊇ core
#   Fill = VNSML (small-cap index) cho slot còn lại tới MAX_SYMBOLS
_CORE_INDEX_GROUPS = ["VN100", "HNX30"]
_FILL_INDEX_GROUP  = "VNSML"


def _fetch_index_members(group: str) -> list[str]:
    """
    Lấy danh sách thành viên 1 index qua Listing.symbols_by_group.
    Trả [] nếu fail (RetryError/empty) — caller tự fallback.
    symbols_by_group trả pandas Series (không phải DataFrame).
    """
    try:
        res = Listing(source="VCI").symbols_by_group(group=group)
    except Exception as e:
        log.warning(f"  ⚠️ symbols_by_group({group}) failed: {type(e).__name__}")
        return []

    if res is None:
        return []
    try:
        if isinstance(res, pd.Series):
            syms = res.dropna().astype(str).tolist()
        elif isinstance(res, pd.DataFrame):
            if res.empty:
                return []
            col = "symbol" if "symbol" in res.columns else res.columns[0]
            syms = res[col].dropna().astype(str).tolist()
        elif isinstance(res, (list, tuple)):
            syms = [str(s) for s in res]
        else:
            return []
    except Exception as e:
        log.warning(f"  ⚠️ parse {group} members: {e}")
        return []

    return [s.strip().upper() for s in syms if s and s.strip()]


def _industry_map_symbols(industry_map: list) -> list[str]:
    """Mã hợp lệ từ industry_map (HSX/HNX, stock only) — dùng cho fill/fallback."""
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
    """
    v8 — Chiến lược B (superset của core):
      1. VN100 + HNX30 (core 130, curated) — add TRƯỚC, luôn đủ
      2. VNSML fill cho ~20 slot còn lại (curated small-cap)
      3. industry_map fill nếu index fill thiếu
      4. industry_map first-N nếu MỌI index empty (ultimate fallback)
    """
    seen: set = set()
    universe: list[str] = []

    def _add(syms: list[str], label: str):
        added = 0
        for s in syms:
            if len(universe) >= MAX_SYMBOLS:
                break
            if _is_valid_stock(s) and s not in seen:
                seen.add(s)
                universe.append(s)
                added += 1
        log.info(f"  + {label}: +{added} (total {len(universe)})")

    # 1) Core curated: VN100 + HNX30
    for grp in _CORE_INDEX_GROUPS:
        if len(universe) >= MAX_SYMBOLS:
            break
        _add(_fetch_index_members(grp), grp)
    core_count = len(universe)

    # 2) Fill: VNSML small-cap (curated)
    if len(universe) < MAX_SYMBOLS:
        _add(_fetch_index_members(_FILL_INDEX_GROUP), _FILL_INDEX_GROUP)

    # 3) Fill: industry_map (nếu vẫn thiếu)
    if len(universe) < MAX_SYMBOLS:
        _add(_industry_map_symbols(industry_map), "industry_map")

    # 4) Ultimate fallback: index API hỏng hoàn toàn
    if not universe:
        log.warning("  ⚠️ ALL index sources empty — fallback industry_map first-N")
        _add(_industry_map_symbols(industry_map), "industry_map(fallback)")

    log.info(f"  Universe: {len(universe)} symbols "
             f"(core VN100+HNX30={core_count}, fill={len(universe)-core_count})")
    return universe


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

    # v11: The current universe comes from authoritative stock lists / stock-typed
    # industry_map. Any legacy `non_stock` marker for these symbols is therefore
    # invalid and must not block finance revalidation for 90 days.
    legacy_non_stock_purged = 0
    for sym in universe:
        entry = cache.get(sym)
        if entry and entry.get("non_stock"):
            cache.pop(sym, None)
            legacy_non_stock_purged += 1
    if legacy_non_stock_purged:
        log.warning(
            f"Purged {legacy_non_stock_purged} legacy non_stock cache entries "
            "for authoritative stock universe"
        )

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
    ignored_non_stock = 0
    fetched_err       = 0
    fetched_vci_fb    = 0  # v7: count VCI fallback usage

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
                log.warning(f"  ⚠️ {sym}: fetch returned None; keeping last-known-good if present")
                continue

            # Defensive v11 guard: fetch_one no longer emits non_stock for no-data.
            # If a future caller returns it unexpectedly, never poison this cache.
            if result.get("non_stock"):
                ignored_non_stock += 1
                log.warning(f"  ⚠️ {sym}: unexpected non_stock result ignored; cache not overwritten")
                continue

            cache[sym] = result
            fetched_ok += 1
            if (result.get("data_status") or {}).get("ratio_source") == "vci_fallback":
                fetched_vci_fb += 1
            try:
                fs     = result.get("finance_score") or {}
                pe     = result.get("ratio",    {}).get("pe")
                roe    = result.get("ratio",    {}).get("roe")
                cfo    = result.get("cashflow", {}).get("cf_operating")
                cfq    = result.get("cashflow", {}).get("cf_quality")
                rsrc   = (result.get("data_status") or {}).get("ratio_source", "?")
                log.info(
                    f"  ✅ {sym} "
                    f"PE={pe} ROE={roe} CFO={cfo} CFq={cfq} "
                    f"score={fs.get('total', 'n/a')} "
                    f"(F={fs.get('fundamental', 'n/a')} "
                    f"CF={fs.get('cashflow', 'n/a')} "
                    f"G={fs.get('growth', 'n/a')}) "
                    f"src={rsrc}"
                )
            except Exception as e:
                log.warning(f"  ⚠️ {sym}: log format error (data đã cache): {e}")

    save_cache(cache)

    log.info(
        f"Done: {fetched_ok} ok ({fetched_vci_fb} via VCI fallback), "
        f"{ignored_non_stock} unexpected non-stock ignored, "
        f"{fetched_err} failed, {len(to_skip)} from cache, "
        f"{legacy_non_stock_purged} legacy non-stock purged. "
        f"Total in cache: {len(cache)} symbols"
    )
    # v9: tổng kết balance_sheet (chi tiết bị silence ở fetch_one).
    if _BALANCE_EMPTY_COUNT[0]:
        log.info(
            f"balance_sheet: {_BALANCE_EMPTY_COUNT[0]} EMPTY "
            f"(lib outage xác nhận — D/E disabled, scoring graceful)"
        )
    log.info("=== step_finance_scan: DONE ===")
    return cache


if __name__ == "__main__":
    run()
