"""
step3_context.py — Daily market context + industry map
========================================================
Output paths: market/context.json, market/industry_map.json
Backward-compat alias: context.json, industry_map.json cũng được ghi

CHANGELOG:
  2026-05-26 — Preserve organ_name + organ_short_name (Bug #11 prep):
    Trước đây industry_map.json chỉ giữ 5 cols: symbol, exchange, type, icb_code, icb_name.
    News step không thể match "Hòa Phát" → HPG vì thiếu company name.

    Fix: thêm organ_name + organ_short_name vào industry_map nếu API có trả.
    Cả 2 fields tùy chọn — nếu Listing API không trả thì save empty.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import logging
import pandas as pd
from vnstock_data import Analytics, Reference, Quote

from utils.helpers import now_ict, last_trading_date, safe_run
from utils.cache import save_json, save_csv
from utils.regime_v3 import shadow_update

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# INDUSTRY MAP
# =====================================================

def get_industry_map() -> pd.DataFrame:
    """
    Build symbol → {icb_code, icb_name, exchange, organ_name, organ_short_name}.

    VCI Reference.industry.list() chỉ trả về ICB hierarchy
    (icb_code, icb_name, icb_level) — KHÔNG có symbol.

    Fix: dùng Listing.symbols_by_exchange() để lấy symbol → icb_code,
    sau đó join với industry.list() để lấy icb_name.

    v2 (2026-05-26): preserve organ_name + organ_short_name nếu có.
    """
    from vnstock_data import Listing

    log.info("=== INDUSTRY MAP ===")

    # Step 1: ICB hierarchy từ Reference
    df_ind = safe_run("industry_list", lambda: Reference().industry.list())
    if df_ind is None or df_ind.empty:
        log.warning("  industry_list trả về empty")
        df_ind = pd.DataFrame()

    log.info(f"  industry_list cols: {list(df_ind.columns) if not df_ind.empty else '[]'}")

    icb_name_map: dict = {}
    if not df_ind.empty and "icb_code" in df_ind.columns and "icb_name" in df_ind.columns:
        for _, row in df_ind.iterrows():
            code = row.get("icb_code")
            name = row.get("icb_name")
            if code and name:
                icb_name_map[str(code)] = str(name)

    # Step 2: Symbol listing từ Listing API
    all_frames = []
    for exchange in ("HSX", "HNX", "UPCOM"):
        df_ex = safe_run(f"symbols_{exchange}",
                 lambda ex=exchange: Listing(source="VCI").symbols_by_exchange(exchange=ex))
        if df_ex is not None and not df_ex.empty:
            df_ex["exchange"] = exchange
            all_frames.append(df_ex)

    if not all_frames:
        df_all_ex = safe_run("symbols_all",
                    lambda: Listing(source="VCI").symbols_by_exchange())
        if df_all_ex is not None and not df_all_ex.empty:
            all_frames.append(df_all_ex)

    if not all_frames:
        log.warning("  Listing.symbols_by_exchange() failed — industry_map will be empty")
        return pd.DataFrame()

    df_sym = pd.concat(all_frames, ignore_index=True)
    log.info(f"  symbols cols: {list(df_sym.columns)}")
    log.info(f"  {len(df_sym)} symbols total")

    # Step 3: Join icb_name vào df_sym
    icb_col = next(
        (c for c in df_sym.columns
         if c.lower() in ("icb_code", "icb_code2", "industry_code", "sector_code")),
        None
    )
    symbol_col = next(
        (c for c in df_sym.columns
         if c.lower() in ("symbol", "ticker", "code")),
        None
    )

    if symbol_col and symbol_col != "symbol":
        df_sym = df_sym.rename(columns={symbol_col: "symbol"})

    if icb_col:
        df_sym["icb_code"] = df_sym[icb_col].astype(str)
        df_sym["icb_name"] = df_sym["icb_code"].map(icb_name_map).fillna("")
    else:
        log.warning(f"  No icb_code column found in {list(df_sym.columns)}")
        df_sym["icb_code"] = ""
        df_sym["icb_name"] = ""

    type_col = next(
        (c for c in df_sym.columns if c.lower() in ("type", "asset_type")),
        None
    )
    if type_col and type_col != "type":
        df_sym = df_sym.rename(columns={type_col: "type"})

    # v2: Detect & preserve organ_name + organ_short_name
    organ_name_col = next(
        (c for c in df_sym.columns
         if c.lower() in ("organ_name", "company_name", "name")),
        None
    )
    organ_short_col = next(
        (c for c in df_sym.columns
         if c.lower() in ("organ_short_name", "short_name", "name_short")),
        None
    )

    if organ_name_col and organ_name_col != "organ_name":
        df_sym = df_sym.rename(columns={organ_name_col: "organ_name"})
    if organ_short_col and organ_short_col != "organ_short_name":
        df_sym = df_sym.rename(columns={organ_short_col: "organ_short_name"})

    # Log presence of name fields for debugging
    has_organ_name = "organ_name" in df_sym.columns
    has_short_name = "organ_short_name" in df_sym.columns
    log.info(f"  organ_name available: {has_organ_name}, "
             f"organ_short_name available: {has_short_name}")

    # Build keep_cols dynamically
    base_cols = ["symbol", "exchange", "type", "icb_code", "icb_name"]
    optional_cols = ["organ_name", "organ_short_name"]
    keep_cols = [c for c in (base_cols + optional_cols) if c in df_sym.columns]

    df_out = df_sym[keep_cols].drop_duplicates("symbol")

    # Fill nan in name fields with empty string for consistent JSON
    for c in ("organ_name", "organ_short_name"):
        if c in df_out.columns:
            df_out[c] = df_out[c].fillna("").astype(str)

    # Debug
    if icb_col and not df_out.empty and "icb_name" in df_out.columns:
        filled = (df_out["icb_name"] != "").sum()
        sample = df_out[df_out["icb_name"] == ""].head(3)[["symbol", "icb_code"]].to_dict("records")
        log.info(f"  Final map: {len(df_out)} symbols, icb_name filled: {filled}")
        if has_organ_name:
            name_filled = (df_out["organ_name"] != "").sum()
            log.info(f"  organ_name filled: {name_filled}/{len(df_out)}")
        if sample:
            log.info(f"  Sample unfilled icb_codes: {sample}")
            sample_keys = list(icb_name_map.keys())[:5]
            log.info(f"  Sample icb_name_map keys: {sample_keys}")
    else:
        log.info(f"  Final map: {len(df_out)} symbols, icb_name filled: 0")

    records = df_out.to_dict(orient="records")
    save_json("market/industry_map.json", records)
    save_json("industry_map.json", records)
    return df_out

# =====================================================
# MARKET CONTEXT — valuation (PE+PB) + VNINDEX trend (regime-aware)
# =====================================================
# CHANGELOG 2026-06-03:
#   FIX 1: market_valuation dùng CẢ pe_pct VÀ pb_pct (trước chỉ pe_pct,
#          bỏ phí pb_pct đã tính → PB=69% mà vẫn ra FAIR).
#   FIX 2: Thêm VNINDEX trend (EMA50/200 + % thay đổi) → market_regime.
#          Lý do: valuation rẻ trong DOWNTREND là "bẫy giá trị" (bắt dao
#          rơi). context_score cần regime để không thưởng điểm khi thị
#          trường rơi tự do. step_scoring đọc market_regime để chấm.

def _vnindex_trend() -> dict:
    """
    Lấy OHLCV VNINDEX 12M → EMA50, EMA200, % thay đổi 5d/20d → regime.
    Trả {} nếu API fail (step_scoring sẽ fallback regime=UNKNOWN → chấm
    thuần valuation như cũ, không crash).
    """
    df = safe_run("vnindex_history",
         lambda: Quote(source="VCI", symbol="VNINDEX")\
                 .history(length="12M", interval="1D"))
    if df is None or df.empty or len(df) < 60:
        return {}

    df = df.copy()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])
    if len(df) < 60:
        return {}

    close = float(df["close"].iloc[-1])
    ema50  = float(df["close"].ewm(span=50,  adjust=False).mean().iloc[-1])
    ema200 = (float(df["close"].ewm(span=200, adjust=False).mean().iloc[-1])
              if len(df) >= 200 else None)

    def _chg(n):
        if len(df) <= n:
            return None
        prev = float(df["close"].iloc[-1 - n])
        return round((close - prev) / prev * 100, 2) if prev else None

    chg_1d  = _chg(1)
    chg_5d  = _chg(5)
    chg_20d = _chg(20)

    # ── Phân loại regime (refined 2026-06-04) ──
    # Kết hợp VỊ TRÍ EMA + MOMENTUM (% thay đổi) để bắt "đang yếu đi" sớm,
    # không chờ tới khi thủng cả EMA200 mới báo DOWNTREND.
    # Bug cũ: VNINDEX dưới EMA50, giảm 6 phiên (-3.8%) nhưng vẫn trên EMA200
    #         → bị xếp SIDEWAYS (0đ). Quá lỏng.
    above_50  = close > ema50
    above_200 = (close > ema200) if ema200 is not None else above_50
    c5  = chg_5d  if chg_5d  is not None else 0.0
    c20 = chg_20d if chg_20d is not None else 0.0

    # DEEP_DOWN: giảm sâu thực sự (dưới cả 2 EMA, hoặc sụp >8% trong 20 phiên)
    if ((not above_50) and (not above_200)) or c20 <= -8:
        regime = "DEEP_DOWN"
    # DOWNTREND: yếu rõ — dưới EMA50 VÀ momentum âm (giảm liên tục)
    elif (not above_50) and (c20 <= -2 or c5 <= -3):
        regime = "DOWNTREND"
    # UPTREND: trên cả 2 EMA VÀ momentum dương
    elif above_50 and above_200 and c20 > 0:
        regime = "UPTREND"
    # Còn lại: đi ngang / chưa rõ
    else:
        regime = "SIDEWAYS"

    return {
        "vnindex_close"   : round(close, 2),
        "vnindex_ema50"   : round(ema50, 2),
        "vnindex_ema200"  : round(ema200, 2) if ema200 is not None else None,
        "vnindex_chg_1d"  : chg_1d,
        "vnindex_chg_5d"  : chg_5d,
        "vnindex_chg_20d" : chg_20d,
        "market_regime"   : regime,
    }


def _valuation_label(pe_pct: float, pb_pct: float) -> str:
    """
    FIX 1: kết hợp PE + PB percentile (trung bình) thay vì chỉ PE.
    <30% CHEAP | >70% EXPENSIVE | còn lại FAIR.
    Dùng avg để 1 chỉ số lệch không chi phối (PE rẻ + PB đắt → FAIR đúng).
    """
    avg_pct = (pe_pct + pb_pct) / 2.0
    if avg_pct < 0.30:
        return "CHEAP"
    if avg_pct > 0.70:
        return "EXPENSIVE"
    return "FAIR"


def get_market_context() -> list:
    log.info("=== MARKET CONTEXT ===")
    df_eval = safe_run("vnindex_evaluation",
               lambda: Analytics().valuation("VNINDEX").evaluation(duration="5Y"))
    if df_eval is None or df_eval.empty:
        return []

    pe_cur  = float(df_eval["pe"].iloc[-1])
    pb_cur  = float(df_eval["pb"].iloc[-1])
    pe_mean = float(df_eval["pe"].mean())
    pb_mean = float(df_eval["pb"].mean())
    pe_pct  = float((df_eval["pe"] <= pe_cur).mean())
    pb_pct  = float((df_eval["pb"] <= pb_cur).mean())

    # FIX 2: VNINDEX trend/regime
    trend = _vnindex_trend()

    rec = {
        "date"             : last_trading_date(),
        "vnindex_pe"       : round(pe_cur,  2),
        "vnindex_pb"       : round(pb_cur,  2),
        "pe_mean_5y"       : round(pe_mean, 2),
        "pb_mean_5y"       : round(pb_mean, 2),
        "pe_min_5y"        : round(float(df_eval["pe"].min()), 2),
        "pe_max_5y"        : round(float(df_eval["pe"].max()), 2),
        "pe_percentile_5y" : round(pe_pct * 100, 1),
        "pb_percentile_5y" : round(pb_pct * 100, 1),
        # FIX 1: PE+PB combined
        "market_valuation" : _valuation_label(pe_pct, pb_pct),
        # FIX 2: trend fields (rỗng nếu API fail → regime=UNKNOWN)
        "market_regime"    : trend.get("market_regime", "UNKNOWN"),
        "vnindex_close"    : trend.get("vnindex_close"),
        "vnindex_ema50"    : trend.get("vnindex_ema50"),
        "vnindex_ema200"   : trend.get("vnindex_ema200"),
        "vnindex_chg_1d"   : trend.get("vnindex_chg_1d"),
        "vnindex_chg_5d"   : trend.get("vnindex_chg_5d"),
        "vnindex_chg_20d"  : trend.get("vnindex_chg_20d"),
        "updated_at"       : now_ict().strftime("%Y-%m-%d %H:%M"),
    }

    # ── SHADOW V4.1 (2026-08-03): regime v3 song song — display/log
    #    only. Scoring V4 vẫn đọc market_regime (v2). ──
    if trend:
        try:
            shadow = shadow_update(trend)
            rec.update(shadow)
            if shadow:
                log.info(f"🔎 SHADOW v3: {shadow.get('regime_display_hint')}")
        except Exception as e:
            log.warning(f"Shadow regime v3 failed (non-fatal): {e}")

    return [rec]

# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT")

    get_industry_map()

    ctx = get_market_context()
    if ctx:
        save_json("market/context.json", ctx)
        save_csv("market/context.csv", pd.DataFrame(ctx))
        save_json("context.json", ctx)
        save_csv("context.csv",   pd.DataFrame(ctx))

        c = ctx[0]
        log.info(
            f"PE={c['vnindex_pe']} (pct={c['pe_percentile_5y']}%) "
            f"PB={c['vnindex_pb']} (pct={c['pb_percentile_5y']}%) "
            f"→ {c['market_valuation']} | regime={c.get('market_regime')} "
            f"(chg20d={c.get('vnindex_chg_20d')}%)"
        )

    log.info("=== STEP 3 DONE ===")
