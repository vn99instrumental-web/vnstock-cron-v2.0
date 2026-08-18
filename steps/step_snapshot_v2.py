"""
step_snapshot_v2.py — Intraday snapshot cho V2 pipeline (fully standalone)
===========================================================================
Copy đầy đủ của step_snapshot.py. KHÔNG import từ step_snapshot.
Thay đổi so với step_snapshot.py: output filenames có suffix _v2 + FF source.

Sync từ step_snapshot.py:
  2026-06-02 — FIX bb_position (Bug #11)
  2026-06-11 — v2 fork: output v2f_deep_raw.json / v2f_ranking.json

Thay đổi RIÊNG của v2 (không có trong v3):
  2026-06-16 — SWITCH FF source CafeF → VCI cho net values.
    Bằng chứng debug_vci_ff.py (2026-06-16, ngoài giờ GD):
      VCI: 5/5 mã trả per-symbol khác nhau (HPG +78.9 / VND -19.8 / SSI -54.7
           / FPT -137.4 / VCB -100.5 tỷ VND).
      CafeF: 5/5 mã trả identical -324.7M (aggregate market, không per-symbol).
    → CafeF foreign_trade() hỏng client-side, không sửa được.
    → get_flow() giờ chỉ 1 lệnh fetch VCI 25d, đọc cả room + net từ cùng DF.
    → Giữ validate_ff_data() làm fail-safe phòng VCI lỗi tương lai.

  2026-06-18 — v2.2 Hướng A: thêm 6 chỉ số từ vnstock_ta library (zero fetch).
    Diagnostic 2026-06-17 (scripts/diag_ta_library.py) đã verify trên HPG/VCB/FPT.
    NEW raw fields trong get_ta():
      Trend:    linreg_20, linreg_slope_pct, aroon_osc, donchian_upper_prev,
                donchian_lower_prev
      Volume:   ad_line, ad_slope_20d_pct, efi_13
      Momentum: willr_14
    Tổng +9 field. Tất cả cache cùng với 11 indicator cũ trong ta_cache.json.

MAINTAINER: Khi step_snapshot.py cập nhật logic → copy lại toàn bộ
body vào đây, giữ nguyên MAIN block cuối với filenames _v2 VÀ
giữ nguyên block get_flow() đã switch sang VCI.
"""
# FORK V2F (full-VN100, monitor cả rổ): I/O dùng prefix v2f_*; universe lấy từ utils.v2f_universe.build_v2f_universe (lấy đủ 100 mã).
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import logging
import random
import time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from vnstock_data import TopStock, Quote, Trading, Market
from vnstock_ta import Indicator

from utils.helpers import (
    now_ict, is_market_open, last_trading_date,
    load_exchange_map, get_exchange,
    safe_run, safe_val, to_float,
    start_str, today_str
)
from utils.cache import save_json, load_json, save_csv
from utils.formatter import clean_for_export, fmt_money_bil
# 2026-06-18: throttle riêng cho VCI (fix 429) — KHÔNG đụng helpers.py (shared v3).
from utils.vci_throttle import vci_safe_run, throttle, is_blocked
# 2026-06-21: VN100 universe (VN100 → recompute gainer/loser → top X) — V2 only.
from utils.v2f_universe import build_v2f_universe

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# 2026-06-18: 10 → 5 (fix 429). Override khi test: VCI_MAX_WORKERS=N
MAX_WORKERS    = int(os.environ.get("VCI_MAX_WORKERS", "5"))

def _to_float_safe(v, default=0.0):
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default
HISTORY_LENGTH = "12M"

FF_FIELDS = [
    "ff_buy_val_5d", "ff_sell_val_5d",
    "ff_net_val_5d", "ff_net_val_20d",
    # ff_room KHÔNG wipe — là field độc lập, không liên quan CafeF net value bug
    "ff_trend", "ff_consistency", "ff_acceleration",
]

# =====================================================
# RANKING / UNIVERSE
# =====================================================
# 2026-06-21: Universe chuyển từ "top 10 gainer + 10 loser TOÀN thị trường"
# sang "VN100 → tính lại gainer/loser TRONG rổ → top X mỗi phía".
# Logic gom về utils/universe_v2.build_v2f_universe() (standalone, V2-only).
# get_ranking() cũ (TopStock VNINDEX limit=10) đã bỏ.

# =====================================================
# SNAPSHOT — Quote(VCI)
# =====================================================

def get_snapshot(symbol: str, market_open: bool) -> dict:
    row = {
        "symbol"   : symbol,
        "exchange" : get_exchange(symbol),
        "snap_time": now_ict().strftime("%H:%M"),
    }

    if market_open:
        df_intra = vci_safe_run(f"intraday {symbol}",
            lambda: Quote(source="VCI", symbol=symbol).intraday(page_size=200))
        if df_intra is not None and not df_intra.empty:
            df_intra["price"]  = pd.to_numeric(df_intra["price"],  errors="coerce")
            df_intra["volume"] = pd.to_numeric(df_intra["volume"], errors="coerce")
            row["price"]      = float(df_intra["price"].iloc[-1])
            row["price_type"] = "realtime"
            buy_mask  = df_intra["match_type"].str.contains("Buy",  case=False, na=False)
            sell_mask = df_intra["match_type"].str.contains("Sell", case=False, na=False)
            buy_vol   = float(df_intra.loc[buy_mask,  "volume"].sum())
            sell_vol  = float(df_intra.loc[sell_mask, "volume"].sum())
            total     = buy_vol + sell_vol
            row["intra_buy_vol"]   = buy_vol
            row["intra_sell_vol"]  = sell_vol
            row["intra_delta"]     = buy_vol - sell_vol
            row["intra_buy_ratio"] = round(buy_vol / total, 2) if total > 0 else None
    else:
        # 2026-06-17: retry 3 lần (trước đây 0 retry → hay fail → price mất →
        #             52W/FairVal/trend dịch điểm ngẫu nhiên giữa các run).
        df_hist = None
        for _att in range(3):
            if is_blocked():
                break
            df_hist = vci_safe_run(f"history {symbol} (attempt {_att+1})",
                lambda: Quote(source="VCI", symbol=symbol).history(length="5D", interval="1D"))
            if df_hist is not None and not df_hist.empty:
                break
            time.sleep(2.0 * (_att + 1) + random.uniform(0, 1.0))  # 2-3, 4-5, 6-7s + jitter
        if df_hist is not None and not df_hist.empty:
            df_hist["close"] = pd.to_numeric(df_hist["close"], errors="coerce")
            row["price"]      = float(df_hist["close"].iloc[-1])
            row["price_type"] = "last_close"
            row["price_date"] = str(df_hist["time"].iloc[-1])[:10]

    if market_open:
        df_ob = safe_run(f"order_book {symbol}",
            lambda: Market().equity(symbol).order_book())
        if df_ob is not None and not df_ob.empty:
            try:
                ob = df_ob.iloc[0]
                for i in (1, 2, 3):
                    row[f"bid_price_{i}"] = to_float(ob.get(f"bid_price_{i}"))
                    row[f"bid_vol_{i}"]   = to_float(ob.get(f"bid_vol_{i}"))
                    row[f"ask_price_{i}"] = to_float(ob.get(f"ask_price_{i}"))
                    row[f"ask_vol_{i}"]   = to_float(ob.get(f"ask_vol_{i}"))
            except Exception as e:
                log.error(f"order_book error {symbol}: {e}")

    return row

# =====================================================
# TA INDICATORS + OHLCV
# =====================================================

def get_ta(symbol: str) -> dict:
    # 2026-06-17 (B): TA CACHE PHIÊN — đảm bảo determinism qua các run.
    # Vấn đề gốc: VCI hay fail ConnectionError theo từng batch → mã ohlcv fail
    # → kích hoạt fallback 3M hoặc ta_error → điểm dịch không kiểm soát giữa runs.
    # Giải pháp: cache phiên gần nhất per-symbol. Fetch ok → ghi cache. Fetch
    # fail (cả 12M và 3M) → đọc cache + đánh dấu _ta_stale_days. TA giữa 2 phiên
    # cách nhau 1-2 ngày khác nhau rất ít → cache fallback gần như identical
    # với data "đúng" + ổn định 100%.
    from utils.cache import load_json as _ld, save_json as _sv
    _TA_CACHE_FILE     = "cache/ta_cache.json"
    _STALE_OK_DAYS     = 2     # ≤2 phiên: tin tưởng full, không hạ confidence
    _STALE_MAX_DAYS    = 5     # >5 phiên: cache quá cũ, coi như không có
    _today             = today_str()   # "YYYY-MM-DD"

    def _stale_days(cached_date: str) -> int:
        """Trả số phiên giữa cached_date và today (đơn giản: số ngày dương lịch)."""
        try:
            from datetime import datetime
            d_cache = datetime.strptime(cached_date, "%Y-%m-%d")
            d_today = datetime.strptime(_today,     "%Y-%m-%d")
            return max(0, (d_today - d_cache).days)
        except Exception:
            return 999

    # ── Fetch 12M (4 retry) ──
    df = None
    for attempt in range(4):
        if is_blocked():   # 2026-06-18: kill switch bật → bỏ retry tránh đốt time
            break
        df = vci_safe_run(f"ohlcv {symbol} (attempt {attempt+1})",
             lambda: Quote(source="VCI", symbol=symbol).history(
                 length=HISTORY_LENGTH, interval="1D"))
        if df is not None and not df.empty and len(df) >= 20:
            break
        if attempt < 3:
            if is_blocked():
                break
            # 2026-06-18: backoff dài hơn + jitter để hồi quota khi gặp 429
            time.sleep(3.0 * (attempt + 1) + random.uniform(0, 1.0))  # 3-4, 6-7, 9-10s

    _ta_window = None
    if df is None or df.empty or len(df) < 20:
        # Fallback 12M fail → thử 3M
        df = vci_safe_run(f"ohlcv_short {symbol}",
             lambda: Quote(source="VCI", symbol=symbol).history(
                 length="3M", interval="1D"))
        if df is None or df.empty or len(df) < 10:
            # 3M cũng fail → ĐỌC CACHE thay vì trả ta_error
            # Đọc silent (không gọi load_json để tránh WARNING khi cache trống lần đầu)
            from config import OUTPUT_DIR
            import json as _json
            cache_path = os.path.join(OUTPUT_DIR, _TA_CACHE_FILE)
            cache_all = {}
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, encoding="utf-8") as _fh:
                        cache_all = _json.load(_fh)
                except Exception:
                    cache_all = {}
            cached = cache_all.get(symbol)
            if cached and cached.get("_cached_date"):
                stale = _stale_days(cached["_cached_date"])
                if stale <= _STALE_MAX_DAYS:
                    log.warning(f"  {symbol}: ohlcv fail toàn bộ → DÙNG CACHE "
                                f"({cached['_cached_date']}, stale={stale}d)")
                    out = dict(cached)
                    out["_ta_stale_days"] = stale
                    out["_ta_from_cache"] = True
                    return out
                else:
                    log.warning(f"  {symbol}: cache quá cũ ({stale}d > {_STALE_MAX_DAYS}d) → ta_error")
            log.warning(f"  {symbol}: TA fetch failed sau retry, no cache → ta_error")
            return {"symbol": symbol, "ta_error": "Không đủ data sau retry"}
        log.info(f"  {symbol}: dùng 3M history ({len(df)} ngày) thay vì 12M")
        _ta_window = "3M"   # 52W high/low từ cửa sổ ngắn → kém tin cậy (scoring sẽ skip 52W)
    else:
        _ta_window = "12M"

    ta         = Indicator(data=df)
    res        = {"symbol": symbol, "_ta_window": _ta_window}
    last_close = float(df["close"].iloc[-1])
    res["_last_close"] = round(last_close, 2)   # để build_one fallback price khi snapshot fail

    ema20 = ta.trend.ema(length=20)
    ema50 = ta.trend.ema(length=50)
    res["ema20"]      = safe_val(ema20)
    res["ema50"]      = safe_val(ema50)
    res["adx"]        = safe_val(ta.trend.adx(length=14))
    res["supertrend"] = safe_val(ta.trend.supertrend(length=10, multiplier=3.0))

    if len(df) >= 200:
        ema200 = ta.trend.ema(length=200)
        res["ema200"] = safe_val(ema200)
    else:
        res["ema200"] = None

    if res["ema20"] and res["ema50"] and res["ema50"] != 0:
        res["ema_cross_pct"] = round(
            (res["ema20"] - res["ema50"]) / res["ema50"] * 100, 2)
    if res.get("ema20") and res["ema20"] != 0:
        res["price_vs_ema20_pct"] = round(
            (last_close - res["ema20"]) / res["ema20"] * 100, 2)
    if res.get("ema200") and res["ema200"] != 0:
        res["price_vs_ema200_pct"] = round(
            (last_close - res["ema200"]) / res["ema200"] * 100, 2)

    res["rsi"]       = safe_val(ta.momentum.rsi(length=14))
    macd = ta.momentum.macd(fast=12, slow=26, signal=9)
    res["macd"]      = safe_val(macd, 0)
    res["macd_sig"]  = safe_val(macd, 1)
    res["macd_hist"] = safe_val(macd, 2)
    stoch = ta.momentum.stoch(k=14, d=3, smooth_k=3)
    res["stoch_k"]   = safe_val(stoch, 0)
    res["stoch_d"]   = safe_val(stoch, 1)

    bb = ta.volatility.bbands(length=20, std=2.0)

    def _bb_col(prefix):
        if bb is None or not hasattr(bb, "columns"):
            return None
        cols = [c for c in bb.columns if c.startswith(prefix)]
        if not cols:
            return None
        val = bb[cols[0]].iloc[-1]
        return round(float(val), 2) if pd.notna(val) else None

    res["bb_lower"] = _bb_col("BBL")
    res["bb_mid"]   = _bb_col("BBM")
    res["bb_upper"] = _bb_col("BBU")
    res["atr"]      = safe_val(ta.volatility.atr(length=14))

    bbp = _bb_col("BBP")
    if bbp is not None:
        res["bb_position"] = round(max(0.0, min(1.0, bbp)), 2)
    elif res["bb_upper"] and res["bb_lower"] and \
         (res["bb_upper"] - res["bb_lower"]) != 0:
        raw = (last_close - res["bb_lower"]) / (res["bb_upper"] - res["bb_lower"])
        res["bb_position"] = round(max(0.0, min(1.0, raw)), 2)

    if res.get("atr") and last_close:
        res["atr_pct"] = round(res["atr"] / last_close * 100, 2)

    res["obv"] = safe_val(ta.volume.obv())
    res["cmf"] = safe_val(ta.volume.cmf(length=20))
    res["mfi"] = safe_val(ta.volume.mfi(length=14))

    # ── v2.2 NEW (Hướng A): 6 chỉ số library vnstock_ta ────────────────
    # Diagnostic 2026-06-17 đã verify shape & column names trên HPG/VCB/FPT.
    # Tất cả tính từ df 12M sẵn có — KHÔNG fetch thêm data.
    #
    #   Trend group:    linreg(20), aroon(14), donchian(20)
    #   Volume group:   ad(), efi(13)
    #   Momentum group: willr(14)
    #
    # Lưu cả raw values + derived (slope_pct, prev_breakout) để scoring đơn giản.

    # Trend — Linear Regression slope (5-bar % change)
    try:
        ls = ta.trend.linreg(length=20)   # Series LINREG_20
        res["linreg_20"] = safe_val(ls)
        if ls is not None and len(ls) >= 6:
            cur, prev = ls.iloc[-1], ls.iloc[-6]
            if pd.notna(cur) and pd.notna(prev) and prev != 0:
                res["linreg_slope_pct"] = round(
                    (cur - prev) / abs(prev) * 100, 2)
    except Exception as e:
        log.warning(f"  {symbol} linreg failed: {e}")

    # Trend — Aroon Oscillator (only osc, raw up/down skipped)
    try:
        aroon = ta.trend.aroon(length=14)  # DF: AROOND_14, AROONU_14, AROONOSC_14
        res["aroon_osc"] = safe_val(aroon, 2)  # AROONOSC_14
    except Exception as e:
        log.warning(f"  {symbol} aroon failed: {e}")

    # Trend — Donchian Channels (lưu PREV day's value cho breakout detection)
    try:
        donchian = ta.volatility.donchian(lower_length=20, upper_length=20)
        if donchian is not None and len(donchian) >= 2:
            dcu_cols = [c for c in donchian.columns if c.startswith("DCU")]
            dcl_cols = [c for c in donchian.columns if c.startswith("DCL")]
            if dcu_cols:
                v = donchian[dcu_cols[0]].iloc[-2]
                if pd.notna(v):
                    res["donchian_upper_prev"] = round(float(v), 2)
            if dcl_cols:
                v = donchian[dcl_cols[0]].iloc[-2]
                if pd.notna(v):
                    res["donchian_lower_prev"] = round(float(v), 2)
    except Exception as e:
        log.warning(f"  {symbol} donchian failed: {e}")

    # Volume — A/D Line + 20d slope %
    try:
        ad_s = ta.volume.ad()  # Series AD (cumulative)
        res["ad_line"] = safe_val(ad_s)
        if ad_s is not None and len(ad_s) >= 21:
            cur, prev = ad_s.iloc[-1], ad_s.iloc[-21]
            if pd.notna(cur) and pd.notna(prev) and prev != 0:
                res["ad_slope_20d_pct"] = round(
                    (cur - prev) / abs(prev) * 100, 2)
    except Exception as e:
        log.warning(f"  {symbol} ad failed: {e}")

    # Volume — Force Index (13)
    try:
        res["efi_13"] = safe_val(ta.volume.efi(length=13))
    except Exception as e:
        log.warning(f"  {symbol} efi failed: {e}")

    # Momentum — Williams %R (14)
    try:
        res["willr_14"] = safe_val(ta.momentum.willr(length=14))
    except Exception as e:
        log.warning(f"  {symbol} willr failed: {e}")
    # ── END v2.2 NEW ──────────────────────────────────────────────────

    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    if len(df) >= 21:
        vol_today  = float(df["volume"].iloc[-1])
        vol_avg_20 = float(df["volume"].iloc[-21:-1].mean())
        if vol_avg_20 > 0:
            res["vol_ma_ratio"] = round(vol_today / vol_avg_20, 2)
            res["vol_today"]    = vol_today
            res["vol_avg_20d"]  = round(vol_avg_20, 0)

    df_5d = df.tail(5)
    ohlcv_5d = []
    avg_vol_5d = float(df_5d["volume"].mean()) if not df_5d.empty else 0
    for _, row in df_5d.iterrows():
        vol = float(row["volume"]) if pd.notna(row["volume"]) else 0
        ohlcv_5d.append({
            "date"  : str(row["time"])[:10],
            "open"  : round(float(row["open"]),  2),
            "high"  : round(float(row["high"]),  2),
            "low"   : round(float(row["low"]),   2),
            "close" : round(float(row["close"]), 2),
            "volume": int(vol),
            "vs_avg5d_pct": round(vol / avg_vol_5d * 100 - 100, 1)
                            if avg_vol_5d > 0 else None,
        })
    res["_ohlcv_5d"] = ohlcv_5d

    # ── 52W High / Low (thực tế từ OHLCV 12M) ──
    if not df.empty:
        df["high"]  = pd.to_numeric(df["high"],  errors="coerce")
        df["low"]   = pd.to_numeric(df["low"],   errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        h52 = df["high"].max()
        l52 = df["low"].min()
        res["high_52w"] = round(float(h52), 2) if pd.notna(h52) else None
        res["low_52w"]  = round(float(l52), 2) if pd.notna(l52) else None

    # ── ROC(10): Rate of Change 10 ngày ──
    if len(df) >= 11:
        close_now = float(df["close"].iloc[-1])
        close_10d = float(df["close"].iloc[-11])
        if close_10d > 0 and pd.notna(close_now) and pd.notna(close_10d):
            res["roc_10"] = round((close_now / close_10d - 1) * 100, 2)

    # ── RS vs VNINDEX proxy: return 20d ──
    if len(df) >= 21:
        close_now = float(df["close"].iloc[-1])
        close_20d = float(df["close"].iloc[-21])
        if close_20d > 0 and pd.notna(close_now) and pd.notna(close_20d):
            res["return_20d"] = round((close_now / close_20d - 1) * 100, 2)

    # ── B: Đánh dấu ĐỂ MAIN GHI CACHE 1 LẦN (tránh race condition concurrent) ──
    # Trước đây mỗi thread tự load+modify+save → 15-20 thread song song ghi
    # cùng 1 file → mất data (thread sau ghi đè thread trước). Giải pháp:
    # chỉ flag _should_cache=True ở đây, MAIN gom tất cả rồi ghi 1 lần sau join.
    if _ta_window == "12M":
        res["_cached_date"]   = _today
        res["_ta_from_cache"] = False
        res["_ta_stale_days"] = 0
        res["_should_cache"]  = True

    return res

# =====================================================
# VNINDEX RETURN — để tính RS chính xác
# =====================================================

def get_vnindex_return(history_length: str = "2M") -> dict:
    """
    Fetch VNINDEX OHLCV → tính return_20d thực.
    Gọi 1 lần trong MAIN, pass vào context hoặc deep_rows.
    """
    for attempt in range(3):
        try:
            throttle()
            df = Quote(source="VCI", symbol="VNINDEX").history(
                length=history_length, interval="1D")
            if df is not None and not df.empty and len(df) >= 5:
                break
            log.warning(f"VNINDEX history empty (attempt {attempt+1}/3)")
        except Exception as e:
            log.warning(f"VNINDEX fetch attempt {attempt+1}/3 failed: {e}")
            df = None
        time.sleep(1.5 * (attempt + 1) + random.uniform(0, 0.5))
    else:
        log.error("VNINDEX fetch failed after 3 attempts")
        return {}
    try:
        if df is None or df.empty or len(df) < 5:
            log.warning("VNINDEX history empty")
            return {}
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        close_now = float(df["close"].iloc[-1])
        res = {"vnindex_close": close_now}
        if len(df) >= 21:
            close_20d = float(df["close"].iloc[-21])
            if close_20d > 0 and pd.notna(close_20d):
                res["vnindex_return_20d"] = round(
                    (close_now / close_20d - 1) * 100, 2)
        if len(df) >= 6:
            close_5d = float(df["close"].iloc[-6])
            if close_5d > 0 and pd.notna(close_5d):
                res["vnindex_return_5d"] = round(
                    (close_now / close_5d - 1) * 100, 2)
        log.info(f"VNINDEX return_20d={res.get('vnindex_return_20d')} "
                 f"return_5d={res.get('vnindex_return_5d')}")
        return res
    except Exception as e:
        log.warning(f"get_vnindex_return error: {e}")
        return {}


# =====================================================
# FLOW — VCI foreign_trade (room + net values)
# =====================================================
# 2026-06-16: switch source CafeF → VCI cho net values.
#   Bằng chứng (debug_vci_ff.py log 2026-06-16):
#     VCI 5/5 mã trả per-symbol khác nhau (HPG +78.9tỷ, VND -19.8tỷ, …)
#     CafeF 5/5 mã trả identical -324.7M (aggregate market, không per-symbol)
#   → CafeF foreign_trade() hỏng client-side, không sửa được.
#   → Dùng VCI cho cả room VÀ net (1 lệnh fetch thay 2).
# Cột VCI: fr_net_value_total / fr_buy_value_matched / fr_sell_value_matched
#          + fr_available_percentage / fr_room_percentage / fr_current_room /
#          fr_total_room + trading_date.
# Giữ validate_ff_data() làm fail-safe phòng khi VCI lỗi tương lai.

def get_flow(symbol: str) -> dict:
    res = {"symbol": symbol}

    # ── 1 lệnh fetch VCI 25 ngày: vừa lấy room (row mới nhất), vừa lấy net (tail 5d/20d) ──
    # fr_available_percentage = % room ngoại còn có thể mua (0.0–1.0)
    # fr_room_percentage      = tổng room cho phép (thường 0.49 hoặc 0.3)
    # fr_net_value_total      = net value per-symbol (VCI trả đúng, đã verify)
    df_vci = vci_safe_run(f"ff_vci {symbol}",
              lambda: Trading(symbol=symbol, source="VCI").foreign_trade(
                  start=start_str(25), end=today_str()))

    if df_vci is not None and not df_vci.empty:
        # Sort ASC theo date để tail(5).sum() = 5 phiên GẦN NHẤT
        if "trading_date" in df_vci.columns:
            df_vci = df_vci.copy()
            df_vci["trading_date"] = pd.to_datetime(df_vci["trading_date"], errors="coerce")
            df_vci = df_vci.sort_values("trading_date", ascending=True)

        # ── ROOM (từ row mới nhất) ──
        row_vci = df_vci.iloc[-1]
        avail = row_vci.get("fr_available_percentage")
        total = row_vci.get("fr_room_percentage")
        if avail is not None and not (isinstance(avail, float) and avail != avail):
            res["ff_room"] = round(float(avail) * 100, 2)
        if total is not None and not (isinstance(total, float) and total != total):
            res["ff_room_max_pct"] = round(float(total) * 100, 2)
        fr_cur  = row_vci.get("fr_current_room")
        fr_tot  = row_vci.get("fr_total_room")
        if fr_cur is not None:
            res["ff_room_raw"] = float(fr_cur)
        if fr_tot is not None:
            res["ff_total_room_raw"] = float(fr_tot)
        log.info(f"  FF room VCI {symbol}: available={res.get('ff_room')}% "
                 f"total_room={res.get('ff_room_max_pct')}%")

        # ── NET / BUY / SELL VALUES (VCI per-symbol đã verify) ──
        rename = {
            "fr_buy_value_matched" : "buy_val",
            "fr_sell_value_matched": "sell_val",
            "fr_net_value_total"   : "net_val",
        }
        for old, new in rename.items():
            if old in df_vci.columns:
                df_vci = df_vci.rename(columns={old: new})

        buy  = pd.to_numeric(df_vci.get("buy_val"),  errors="coerce").dropna() \
               if "buy_val"  in df_vci.columns else pd.Series(dtype=float)
        sell = pd.to_numeric(df_vci.get("sell_val"), errors="coerce").dropna() \
               if "sell_val" in df_vci.columns else pd.Series(dtype=float)
        net  = pd.to_numeric(df_vci.get("net_val"),  errors="coerce").dropna() \
               if "net_val"  in df_vci.columns else pd.Series(dtype=float)

        if not net.empty:
            res["ff_buy_val_5d"]  = float(buy.tail(5).sum())  if not buy.empty  else 0.0
            res["ff_sell_val_5d"] = float(sell.tail(5).sum()) if not sell.empty else 0.0
            res["ff_net_val_5d"]  = float(net.tail(5).sum())
            res["ff_net_val_20d"] = float(net.sum())

            if len(net) >= 5:
                x     = np.arange(len(net))
                y     = net.fillna(0).values
                slope = np.polyfit(x, y, 1)[0]
                res["ff_trend"]       = round(float(slope) / 1e9, 2)
                res["ff_consistency"] = round((net > 0).sum() / len(net), 2)
                ff_5d_avg  = net.tail(5).mean()
                ff_20d_avg = net.mean()
                res["ff_acceleration"] = round(
                    float(ff_5d_avg - ff_20d_avg) / 1e9, 2) \
                    if ff_20d_avg != 0 else 0.0

            log.info(f"  FF VCI {symbol}: net5d={res.get('ff_net_val_5d'):.0f} "
                     f"net20d={res.get('ff_net_val_20d'):.0f} rows={len(net)}")
        else:
            log.warning(f"  FF VCI {symbol}: không tìm thấy cột net (cols={list(df_vci.columns)[:8]})")
    else:
        log.warning(f"  FF VCI {symbol}: empty/None — ff_score sẽ = 0 cho mã này")

    # ── Prop Trade (Tự doanh CTCK) — Smart Money signal ──
    # VCI prop_trade(): tự doanh mua/bán ròng 25 ngày
    # 2026-06-18: quiet=True — mã KHÔNG có giao dịch tự doanh → vnstock_data trả
    #   DataFrame cột rỗng/NaN → lib tự gọi .str trên cột non-string → AttributeError
    #   ("Can only use .str accessor with string values!"). Đây là LIB BUG, không
    #   sửa được client-side; vci_safe_run catch → trả None → mã KHÔNG bị mất, chỉ
    #   thiếu pt_net_val. quiet=True để khỏi spam traceback. end=last_trading_date()
    #   thay today_str() để không request ngày chưa giao dịch (chạy ngoài giờ).
    df_pt = vci_safe_run(f"prop_trade {symbol}",
              lambda: Trading(symbol=symbol, source="VCI").prop_trade(
                  start=start_str(25), end=last_trading_date()),
              quiet=True)
    if df_pt is not None and not df_pt.empty:
        try:
            # VCI prop_trade() trả cột 'total_trade_net_value' (đã confirm từ debug)
            # Fallback: tìm cột chứa 'net_value' nếu API đổi tên
            PREFERRED = "total_trade_net_value"
            net_col = PREFERRED if PREFERRED in df_pt.columns else                       next((c for c in df_pt.columns
                            if "net" in c.lower() and "value" in c.lower()), None)
            if net_col:
                net_pt = pd.to_numeric(df_pt[net_col], errors="coerce").dropna()
                if not net_pt.empty:
                    res["pt_net_val_5d"]  = float(net_pt.tail(5).sum())
                    res["pt_net_val_20d"] = float(net_pt.sum())
                    if len(net_pt) >= 5:
                        x = np.arange(len(net_pt))
                        slope = np.polyfit(x, net_pt.fillna(0).values, 1)[0]
                        res["pt_trend"] = round(float(slope) / 1e9, 2)
                    log.info(f"  PropTrade {symbol}: "
                             f"net5d={res['pt_net_val_5d']:.0f} "
                             f"net20d={res['pt_net_val_20d']:.0f}")
            else:
                log.debug(f"  PropTrade {symbol}: no net_value column in {df_pt.columns.tolist()}")
        except Exception as e:
            log.warning(f"  PropTrade {symbol} parse error: {e}")

    # ── Insider: limit=20 để phân biệt được số lượng giao dịch ──
    df_id = vci_safe_run(f"insider_deal_vci {symbol}",
             lambda: Trading(symbol=symbol, source="VCI").insider_deal(limit=20))
    if df_id is None:
        df_id = safe_run(f"insider_deal_cafef {symbol}",
                 lambda: Trading(symbol=symbol, source="CafeF").insider_deal(limit=20))
        if df_id is not None and not df_id.empty:
            df_id = df_id.rename(columns={
                "transaction_man"         : "trader_name",
                "transaction_man_position": "trader_position",
                "transaction_note"        : "action_type",
            })

    if df_id is not None and not df_id.empty:
        # Phân tích 90 ngày gần nhất nếu có cột ngày
        date_col = next((c for c in df_id.columns
                         if "date" in c.lower() or "time" in c.lower()), None)
        if date_col:
            try:
                df_id[date_col] = pd.to_datetime(df_id[date_col], errors="coerce")
                cutoff = pd.Timestamp.now() - pd.Timedelta(days=90)
                df_90d = df_id[df_id[date_col] >= cutoff]
                df_id  = df_90d if not df_90d.empty else df_id
            except Exception:
                pass

        action_col = "action_type" if "action_type" in df_id.columns else None
        if action_col:
            buy_kw  = ["mua", "buy", "purchase", "acqui"]
            sell_kw = ["bán", "sell", "dispos", "transfer"]
            actions = df_id[action_col].astype(str).str.lower()
            buy_cnt  = actions.apply(lambda x: any(k in x for k in buy_kw)).sum()
            sell_cnt = actions.apply(lambda x: any(k in x for k in sell_kw)).sum()
            res["insider_buy_count"]  = int(buy_cnt)
            res["insider_sell_count"] = int(sell_cnt)
            res["insider_count"]      = len(df_id)
            res["insider_latest"]     = str(df_id[action_col].iloc[0])
        else:
            res["insider_count"]  = len(df_id)
        res["insider_name"] = str(df_id["trader_name"].iloc[0]) \
                              if "trader_name" in df_id.columns else None

    return res

# =====================================================
# ENRICH FINANCE
# =====================================================

def _calc_eps_consistency(entry: dict) -> int | None:
    """
    Tính số quý liên tiếp lợi nhuận tăng YoY (dương) hoặc giảm (âm).
    Đọc từ entry["income"]["quarters"] nếu finance_scan lưu nhiều kỳ.
    Fallback: dùng is_profit_growth_yoy (1 quý) → trả 1 hoặc -1.
    """
    if not entry:
        return None
    quarters = entry.get("income", {}).get("quarters", [])
    if quarters and len(quarters) >= 2:
        # quarters sorted newest first — đếm streak
        streak = 0
        for q in quarters:
            yoy = q.get("profit_growth_yoy")
            if yoy is None:
                break
            if streak == 0:
                streak = 1 if yoy > 0 else -1
            elif streak > 0 and yoy > 0:
                streak += 1
            elif streak < 0 and yoy <= 0:
                streak -= 1
            else:
                break
        return streak

    # Fallback: 1 quý
    yoy = entry.get("income", {}).get("profit_growth_yoy")
    if yoy is None:
        return None
    return 1 if yoy > 0 else -1


def enrich_finance(symbol: str, fin_cache: dict) -> dict:
    entry = fin_cache.get(symbol)

    if not entry:
        log.info(f"  Finance cache miss: {symbol} — lazy fetch")
        try:
            from steps.step_finance_scan_vci import fetch_one
            entry = fetch_one(symbol)
            if entry:
                fin_cache[symbol] = entry
                try:
                    from steps.step_finance_scan_vci import load_cache, save_cache
                    cache = load_cache()
                    cache[symbol] = entry
                    save_cache(cache)
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"  Lazy finance fetch failed {symbol}: {e}")

    if not entry:
        return {}

    r = entry.get("ratio", {})
    i = entry.get("income", {})
    b = entry.get("balance", {})
    c = entry.get("cashflow", {})

    return {
        "r_period"          : entry.get("period", ""),
        "r_pe"              : r.get("pe"),
        "r_pb"              : r.get("pb"),
        "r_roe"             : r.get("roe"),
        "r_roa"             : r.get("roa"),
        "r_eps"             : r.get("eps"),
        "r_bvps"            : r.get("bvps"),
        "r_beta"            : r.get("beta"),
        "r_div_yield"       : r.get("div_yield"),
        "r_gross_margin"    : r.get("gross_margin"),
        "r_net_margin"      : r.get("net_margin"),
        "r_quick_ratio"     : r.get("quick_ratio"),
        "r_interest_cov"    : r.get("interest_cov"),
        "r_ev_ebitda"       : r.get("ev_ebitda"),
        "is_revenue"           : i.get("revenue"),
        "is_gross_profit"      : i.get("gross_profit"),
        "is_net_profit"        : i.get("net_profit"),
        "is_operating_profit"  : i.get("operating_profit"),
        "is_eps"               : i.get("eps"),
        "is_rev_growth"        : i.get("rev_growth_qoq"),
        "is_profit_growth"     : i.get("profit_growth_qoq"),
        "is_rev_growth_yoy"    : i.get("rev_growth_yoy"),
        "is_profit_growth_yoy" : i.get("profit_growth_yoy"),
        # EPS consistency: số quý liên tiếp lợi nhuận tăng YoY
        # income.quarters = list of {"period", "net_profit", "profit_growth_yoy"}
        # nếu finance cache lưu nhiều kỳ
        "eps_consistency"      : _calc_eps_consistency(entry),
        "bs_total_assets"   : b.get("total_assets"),
        "bs_equity"         : b.get("equity"),
        "bs_total_liab"     : b.get("total_liab"),
        "bs_short_debt"     : b.get("short_debt"),
        "bs_long_debt"      : b.get("long_debt"),
        "bs_debt_to_equity" : b.get("debt_to_equity"),
        "cf_operating"      : c.get("cf_operating"),
        "cf_investing"      : c.get("cf_investing"),
        "cf_financing"      : c.get("cf_financing"),
        "cf_free"           : c.get("cf_free"),
        "cf_quality_ratio"  : c.get("cf_quality"),
        "finance_score"       : entry.get("finance_score", {}).get("total"),
        "finance_score_fund"  : entry.get("finance_score", {}).get("fundamental"),
        "finance_score_cf"    : entry.get("finance_score", {}).get("cashflow"),
        "finance_score_growth": entry.get("finance_score", {}).get("growth"),
    }

# =====================================================
# BUILD ONE SYMBOL
# =====================================================

def build_one(symbol: str, group: str, market_open: bool,
              industry_map: list, fin_cache: dict) -> dict:
    try:
        snap    = get_snapshot(symbol, market_open)
        ta      = get_ta(symbol)
        flow    = get_flow(symbol)
        finance = enrich_finance(symbol, fin_cache)

        ind_row  = next(
            (r for r in industry_map
             if r.get("symbol") == symbol or r.get("ticker") == symbol),
            {}
        )
        row = {
            "symbol"  : symbol,
            "group"   : group,
            "exchange": get_exchange(symbol),
            "time"    : now_ict().strftime("%Y-%m-%d %H:%M"),
            "date"    : today_str(),
            **{k: v for k, v in snap.items()    if k != "symbol"},
            **{k: v for k, v in ta.items()      if k != "symbol"},
            **{k: v for k, v in flow.items()    if k != "symbol"},
            **{k: v for k, v in finance.items() if k != "symbol"},
            "industry": ind_row.get("icb_name", ""),
            "icb_code": ind_row.get("icb_code", ""),
            "organ_short_name": ind_row.get("organ_short_name", "") or "",
            "organ_name"      : ind_row.get("organ_name", "") or "",
        }

        # ── PRICE FALLBACK CHAIN (2026-06-17) ──────────────────────────
        # Nguyên nhân non-determinism: get_snapshot 5D history fail → price
        # mất → score_52w_high / score_fair_value / trend bail → điểm dịch
        # ngẫu nhiên giữa các run. get_ta (12M) là SUPERSET của 5D nên luôn
        # có last_close → dùng làm fallback để price LUÔN tồn tại.
        if row.get("price") is None and ta.get("_last_close") is not None:
            row["price"]          = ta["_last_close"]
            row["price_type"]     = "ta_last_close"
            row["_price_fallback"] = True
            log.warning(f"  {symbol}: snapshot price fail → fallback ta last_close={row['price']}")

        # ff_room đã được tính từ VCI (fr_available_percentage × 100) trong get_flow
        # Không cần tính từ KBS — VCI fr_available_percentage chính xác hơn
        log.info(
            f"  ✅ {symbol} ({group}) "
            f"RSI={row.get('rsi')} PE={row.get('r_pe')} "
            f"FF5d={fmt_money_bil(row.get('ff_net_val_5d'))}tỷ "
            f"VolRatio={row.get('vol_ma_ratio')} "
            f"D/E={row.get('bs_debt_to_equity')}"
        )
        return row

    except Exception as e:
        log.error(f"  ❌ {symbol}: {e}")
        import traceback; traceback.print_exc()
        return {
            "symbol"  : symbol,
            "group"   : group,
            "exchange": get_exchange(symbol),
            "time"    : now_ict().strftime("%Y-%m-%d %H:%M"),
            "date"    : today_str(),
            "error"   : str(e),
        }

# =====================================================
# FF identical validation gate
# =====================================================

def validate_ff_data(deep_rows: list[dict]) -> list[dict]:
    if not deep_rows:
        return deep_rows

    nets_5d  = [r.get("ff_net_val_5d")  for r in deep_rows
                if r.get("ff_net_val_5d")  is not None]
    nets_20d = [r.get("ff_net_val_20d") for r in deep_rows
                if r.get("ff_net_val_20d") is not None]

    suspicious = False
    reason     = ""

    if len(nets_5d) >= 3 and len(set(nets_5d)) == 1:
        suspicious = True
        reason     = (f"identical ff_net_val_5d={nets_5d[0]:.0f} "
                      f"across {len(nets_5d)} symbols")
    elif len(nets_20d) >= 3 and len(set(nets_20d)) == 1:
        suspicious = True
        reason     = (f"identical ff_net_val_20d={nets_20d[0]:.0f} "
                      f"across {len(nets_20d)} symbols")

    if not suspicious:
        log.info(f"  ✅ FF data quality OK: "
                 f"{len(nets_5d)} symbols, "
                 f"{len(set(nets_5d))} unique net_5d values")
        return deep_rows

    log.error(f"🚨 FF DATA BUG DETECTED: {reason}")
    affected = 0
    for r in deep_rows:
        had_data = any(r.get(k) is not None for k in FF_FIELDS)
        for k in FF_FIELDS:
            r[k] = None
        r["ff_data_invalid"] = True
        if had_data:
            affected += 1
    log.error(f"   {affected}/{len(deep_rows)} symbols had FF data wiped.")
    return deep_rows


# =====================================================
# MAIN — chỉ khác step_snapshot.py ở output filenames (_v2)
# =====================================================

if __name__ == "__main__":
    trading = is_market_open()
    log.info(f"=== SNAPSHOT V2 START ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    log.info(f"Market open: {trading}")
    log.info(f"History    : {HISTORY_LENGTH} (for EMA200)")

    load_exchange_map()

    industry_map  = load_json("industry_map.json") or \
                    load_json("market/industry_map.json") or []
    fin_cache_raw = load_json("finance/cache.json") or {}
    fin_cache     = fin_cache_raw.get("symbols", fin_cache_raw) \
                    if isinstance(fin_cache_raw, dict) else {}
    log.info(f"Finance cache: {len(fin_cache)} symbols loaded")

    # Fetch VNINDEX return + Market breadth (% VN100 trên EMA20)
    vnindex_info = get_vnindex_return()
    if vnindex_info and vnindex_info.get('vnindex_return_20d') is not None:
        log.info(f"✅ VNINDEX return_20d={vnindex_info.get('vnindex_return_20d'):.2f}% "
                 f"return_5d={vnindex_info.get('vnindex_return_5d')}")
    else:
        log.warning(f"⚠️ VNINDEX return not available: {vnindex_info} — RS sẽ dùng fallback")

    # Market breadth: tính từ universe đã chọn (~2*VN100_TOP_X mã)
    # Đây là proxy cho breadth toàn VN100; kết quả pass sang scoring qua vnindex_info

    # ── V2 universe: VN100 → tính lại gainer/loser trong rổ → top X mỗi phía ──
    # symbol_jobs : [(symbol, "GAINER"/"LOSER")] cho pass 2 (TA / FF / depth)
    # ranking_rows: schema price_change_percent_1d / price_change_1d /
    #               accumulated_value → scoring._attach_daily_change đọc trực tiếp.
    symbol_jobs, ranking_rows = build_v2f_universe()
    if not symbol_jobs:
        log.error("Universe rỗng (VN100/TopStock fail) — dừng, không có mã để chấm.")
        sys.exit(1)

    # Enrich exchange + date cho v2f_ranking.json (parity schema cũ + dashboard)
    _today_rank = today_str()
    for _r in ranking_rows:
        _r["exchange"] = get_exchange(_r["symbol"])
        _r["date"]     = _today_rank

    all_deep_rows = []

    log.info(f"Fetching {len(symbol_jobs)} symbols concurrently "
             f"(workers={MAX_WORKERS})...")

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(
                build_one, sym, grp, trading, industry_map, fin_cache
            ): (sym, grp)
            for sym, grp in symbol_jobs
        }
        for future in as_completed(future_map):
            sym, grp = future_map[future]
            try:
                results[sym] = future.result()
            except Exception as e:
                log.error(f"Future error {sym}: {e}")

    for sym, grp in symbol_jobs:
        if sym in results:
            row = results[sym]
            # Enrich vnindex return vào từng row để scoring dùng
            if vnindex_info:
                row["vnindex_return_20d"] = vnindex_info.get("vnindex_return_20d")
                row["vnindex_return_5d"]  = vnindex_info.get("vnindex_return_5d")
            all_deep_rows.append(row)

    # ── Market breadth từ deep_rows (proxy: 20 symbols universe) ──
    if all_deep_rows and vnindex_info is not None:
        n_above_ema20 = sum(
            1 for r in all_deep_rows
            if r.get("ema20") and r.get("price") and
               _to_float_safe(r.get("price")) >= _to_float_safe(r.get("ema20"))
        )
        breadth_pct = round(n_above_ema20 / len(all_deep_rows) * 100, 1)
        vnindex_info["market_breadth_pct"] = breadth_pct
        log.info(f"Market breadth (universe proxy): {n_above_ema20}/{len(all_deep_rows)} = {breadth_pct}%")

    log.info("=== DATA QUALITY: FF validation ===")
    all_deep_rows = validate_ff_data(all_deep_rows)

    # ── FF-INTRADAY (SHADOW) — khối ngoại TRONG PHIÊN / tổng GTGD ──────────
    # price_board 1 lệnh bulk (verified 2026-08-07) → gắn ff_intra_* metadata.
    # KHÔNG vào scoring (cap=0) — chỉ để ghi ledger đối chiếu outcome sau.
    # Fail-soft: lỗi → bỏ qua, KHÔNG chặn pipeline.
    try:
        from utils.ff_intraday import (fetch_intraday_ff, session_fraction,
                                        score_ff_intra, ff_intra_flag)
        _ffi_syms = [r.get("symbol") for r in all_deep_rows if r.get("symbol")]
        _ffi_map  = fetch_intraday_ff(_ffi_syms)
        _ffi_frac = session_fraction(now_ict())
        _ffi_n = 0
        for r in all_deep_rows:
            d = _ffi_map.get(r.get("symbol"))
            if not d:
                continue
            r["ff_intra_net"]   = d.get("ff_intra_net")
            r["ff_intra_gtgd"]  = d.get("ff_intra_gtgd")
            r["ff_intra_ratio"] = d.get("ff_intra_ratio")
            r["ff_intra_frac"]  = _ffi_frac
            _pts, _ = score_ff_intra(d.get("ff_intra_ratio"), _ffi_frac)
            r["ff_intra_pts"]   = _pts
            # Cờ "NN gom mạnh" (PRE-REGISTER) — metadata mọi engine thấy;
            # chỉ V4 cộng ff_intra_flag_pts vào score_trade (S2).
            _flag, _flag_pts = ff_intra_flag(d.get("ff_intra_net"),
                                             d.get("ff_intra_ratio"), _ffi_frac)
            r["ff_intra_strong_buy"]  = (_flag == 1)
            r["ff_intra_strong_sell"] = (_flag == -1)
            r["ff_intra_flag_pts"]    = _flag_pts
            _ffi_n += 1
        log.info(f"FF-intraday (shadow): {_ffi_n}/{len(all_deep_rows)} mã có ratio "
                 f"(frac={_ffi_frac})")
    except Exception as _ffi_e:
        log.warning(f"FF-intraday shadow skip (không chặn pipeline): {_ffi_e}")

    # ── B (2026-06-17): GỘP GHI TA CACHE 1 LẦN ở MAIN (an toàn race) ──
    # Mỗi thread get_ta chỉ flag _should_cache=True; MAIN gom tất cả ở đây và
    # ghi 1 lệnh save_json duy nhất → an toàn 100% với mọi mức concurrent.
    try:
        from utils.cache import load_json as _ld_main, save_json as _sv_main
        from datetime import datetime as _dt
        _today_str = today_str()
        _TA_CACHE_FILE = "cache/ta_cache.json"

        _cache_all = _ld_main(_TA_CACHE_FILE) or {}
        _new_count = 0
        for r in all_deep_rows:
            if not r.get("_should_cache"):
                continue
            sym = r.get("symbol")
            if not sym:
                continue
            # Strip các field meta không cần cache
            entry = {k: v for k, v in r.items()
                     if not k.startswith("_should_cache")}
            _cache_all[sym] = entry
            _new_count += 1

        # TTL cleanup: bỏ entries >30 ngày
        def _days_old(d_str: str) -> int:
            try:
                return (_dt.strptime(_today_str, "%Y-%m-%d") -
                        _dt.strptime(d_str, "%Y-%m-%d")).days
            except Exception:
                return 999
        _cache_all = {
            k: v for k, v in _cache_all.items()
            if isinstance(v, dict) and _days_old(v.get("_cached_date", "1970-01-01")) <= 30
        }

        _sv_main(_TA_CACHE_FILE, _cache_all)
        log.info(f"TA cache: cập nhật {_new_count} mã (tổng {len(_cache_all)} entries trong file)")
    except Exception as _e:
        log.warning(f"TA cache write fail: {_e}")

    # ── V2: output filenames có suffix _v2 ──
    if ranking_rows:
        df_rank_all = pd.DataFrame(ranking_rows)
        save_json("v2f_ranking.json", ranking_rows)
        save_csv("v2f_ranking.csv",   clean_for_export(df_rank_all))
        log.info(f"Saved v2f_ranking.json ({len(ranking_rows)} rows)")

    if all_deep_rows:
        df_deep = pd.DataFrame(all_deep_rows)
        save_json("v2f_deep_raw.json", df_deep.to_dict(orient="records"))
        df_export = df_deep.drop(columns=["_ohlcv_5d"], errors="ignore")
        df_clean  = clean_for_export(df_export)
        save_json("v2f_deep.json", df_clean.to_dict(orient="records"))
        save_csv("v2f_deep.csv",   df_clean)
        log.info(f"Saved v2f_deep_raw.json ({len(df_deep)} rows, "
                 f"{len(df_deep.columns)} cols)")

    log.info("=== SNAPSHOT V2 DONE ===")
