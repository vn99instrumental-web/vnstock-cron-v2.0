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
from vnstock_data import Analytics, Reference

from utils.helpers import now_ict, last_trading_date, safe_run
from utils.cache import save_json, save_csv

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
# MARKET CONTEXT — Analytics(VND) 5Y PE/PB
# =====================================================

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

    return [{
        "date"             : last_trading_date(),
        "vnindex_pe"       : round(pe_cur,  2),
        "vnindex_pb"       : round(pb_cur,  2),
        "pe_mean_5y"       : round(pe_mean, 2),
        "pb_mean_5y"       : round(pb_mean, 2),
        "pe_min_5y"        : round(float(df_eval["pe"].min()), 2),
        "pe_max_5y"        : round(float(df_eval["pe"].max()), 2),
        "pe_percentile_5y" : round(pe_pct * 100, 1),
        "pb_percentile_5y" : round(pb_pct * 100, 1),
        "market_valuation" : "CHEAP"     if pe_pct < 0.3 else
                             "EXPENSIVE" if pe_pct > 0.7 else "FAIR",
        "updated_at"       : now_ict().strftime("%Y-%m-%d %H:%M"),
    }]

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
            f"PE={c['vnindex_pe']} "
            f"pct={c['pe_percentile_5y']}% "
            f"→ {c['market_valuation']}"
        )

    log.info("=== STEP 3 DONE ===")
