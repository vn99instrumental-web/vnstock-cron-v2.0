"""
step_context_refresh.py — Intraday VNINDEX price/trend refresh
==============================================================
Chạy trong cron_intraday.yml TRƯỚC step_snapshot.py.

Nhiệm vụ:
  - Load context.json hiện có (do cron_daily ghi lúc 08:00 ICT)
  - Fetch VNINDEX history 12M → tính close, EMA50, EMA200, chg_1d/5d/20d,
    market_regime
  - Overwrite đúng các field realtime, GIỮ NGUYÊN PE/PB/valuation từ daily
  - Ghi lại context.json + market/context.json

KHÔNG đụng đến:
  vnindex_pe, vnindex_pb, pe_mean_5y, pb_mean_5y,
  pe_min_5y, pe_max_5y, pe_percentile_5y, pb_percentile_5y,
  market_valuation  ← những field này chỉ đổi khi PE/PB thay đổi

Fallback:
  - Nếu context.json chưa tồn tại (first run) → tạo record mới với
    PE/PB fields = None
  - Nếu API fail → giữ nguyên context.json cũ, chỉ update updated_at
    để biết script đã chạy

CHANGELOG:
  v1 (2026-06-08) — initial: tách từ step3_context.py, chỉ phần trend
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
from vnstock_data import Quote

from utils.helpers import now_ict, safe_run
from utils.cache import load_json, save_json, save_csv
from utils.regime_v3 import shadow_update

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger(__name__)

# =====================================================
# REALTIME FIELDS — chỉ những field này bị overwrite
# =====================================================
REALTIME_FIELDS = {
    "vnindex_close",
    "vnindex_ema50",
    "vnindex_ema200",
    "vnindex_chg_1d",
    "vnindex_chg_5d",
    "vnindex_chg_20d",
    "market_regime",
    "updated_at",
    # ── SHADOW V4.1 (2026-08-03) — display/log only, KHÔNG vào scoring ──
    "market_regime_v3",
    "market_regime_v3_raw",
    "regime_v3_pending",
    "regime_display_hint",
}


def _fetch_vnindex_trend() -> dict | None:
    """
    Fetch VNINDEX OHLCV 12M, tính EMA50/200, % thay đổi, regime.
    Trả None nếu API fail hoặc không đủ data.
    Logic phân loại regime giống hệt step3_context._vnindex_trend()
    để hai luồng nhất quán.
    """
    df = safe_run(
        "vnindex_history",
        lambda: Quote(source="VCI", symbol="VNINDEX")
                .history(length="12M", interval="1D")
    )
    if df is None or df.empty or len(df) < 60:
        log.warning("VNINDEX history: không đủ data (cần ≥60 nến)")
        return None

    df = df.copy()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"])
    if len(df) < 60:
        log.warning("VNINDEX history: sau dropna còn < 60 nến")
        return None

    close  = float(df["close"].iloc[-1])
    ema50  = float(df["close"].ewm(span=50,  adjust=False).mean().iloc[-1])
    ema200 = (
        float(df["close"].ewm(span=200, adjust=False).mean().iloc[-1])
        if len(df) >= 200 else None
    )

    def _chg(n: int) -> float | None:
        if len(df) <= n:
            return None
        prev = float(df["close"].iloc[-1 - n])
        return round((close - prev) / prev * 100, 2) if prev else None

    chg_1d  = _chg(1)
    chg_5d  = _chg(5)
    chg_20d = _chg(20)

    # ── Phân loại regime (giống step3_context v2 — refined 2026-06-04) ──
    above_50  = close > ema50
    above_200 = (close > ema200) if ema200 is not None else above_50
    c5  = chg_5d  if chg_5d  is not None else 0.0
    c20 = chg_20d if chg_20d is not None else 0.0

    if ((not above_50) and (not above_200)) or c20 <= -8:
        regime = "DEEP_DOWN"
    elif (not above_50) and (c20 <= -2 or c5 <= -3):
        regime = "DOWNTREND"
    elif above_50 and above_200 and c20 > 0:
        regime = "UPTREND"
    else:
        regime = "SIDEWAYS"

    log.info(
        f"VNINDEX close={close} EMA50={round(ema50,2)} "
        f"EMA200={round(ema200,2) if ema200 else 'N/A'} "
        f"chg_1d={chg_1d}% chg_5d={chg_5d}% chg_20d={chg_20d}% "
        f"→ {regime}"
    )

    return {
        "vnindex_close"   : round(close, 2),
        "vnindex_ema50"   : round(ema50, 2),
        "vnindex_ema200"  : round(ema200, 2) if ema200 is not None else None,
        "vnindex_chg_1d"  : chg_1d,
        "vnindex_chg_5d"  : chg_5d,
        "vnindex_chg_20d" : chg_20d,
        "market_regime"   : regime,
    }


def _empty_context_record() -> dict:
    """Skeleton record dùng khi context.json chưa tồn tại (first run)."""
    return {
        "date"               : now_ict().strftime("%Y-%m-%d"),
        "vnindex_pe"         : None,
        "vnindex_pb"         : None,
        "pe_mean_5y"         : None,
        "pb_mean_5y"         : None,
        "pe_min_5y"          : None,
        "pe_max_5y"          : None,
        "pe_percentile_5y"   : None,
        "pb_percentile_5y"   : None,
        "market_valuation"   : "FAIR",   # safe default cho scoring
        "market_regime"      : "UNKNOWN",
        "vnindex_close"      : None,
        "vnindex_ema50"      : None,
        "vnindex_ema200"     : None,
        "vnindex_chg_1d"     : None,
        "vnindex_chg_5d"     : None,
        "vnindex_chg_20d"    : None,
        "updated_at"         : now_ict().strftime("%Y-%m-%d %H:%M"),
    }


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    log.info(f"=== CONTEXT REFRESH ===")
    log.info(f"Time: {now_ict():%Y-%m-%d %H:%M:%S} ICT")

    # 1. Load context hiện có
    existing = load_json("market/context.json")
    if existing and isinstance(existing, list) and len(existing) > 0:
        record = existing[0].copy()
        log.info(
            f"Loaded existing context — "
            f"PE={record.get('vnindex_pe')} "
            f"PB={record.get('vnindex_pb')} "
            f"valuation={record.get('market_valuation')} "
            f"(last updated: {record.get('updated_at')})"
        )
    else:
        log.warning("context.json không tìm thấy — tạo skeleton record mới")
        record = _empty_context_record()

    # 2. Fetch trend mới
    trend = _fetch_vnindex_trend()

    if trend is not None:
        # Overwrite đúng REALTIME_FIELDS, giữ nguyên PE/PB/valuation
        for field, value in trend.items():
            record[field] = value

        # ── SHADOW V4.1 (2026-08-03): regime v3 song song, chỉ ghi
        #    field hiển thị + append market/regime_v3_log.json.
        #    Scoring/gate V4 vẫn đọc market_regime (v2) — KHÔNG đổi. ──
        try:
            shadow = shadow_update(trend)
            for field, value in shadow.items():
                record[field] = value
            if shadow:
                log.info(
                    f"🔎 SHADOW v3: raw={shadow['market_regime_v3_raw']} "
                    f"eff={shadow['market_regime_v3']} "
                    f"pending={shadow['regime_v3_pending']} "
                    f"| hint: {shadow['regime_display_hint']}"
                )
        except Exception as e:
            log.warning(f"Shadow regime v3 failed (non-fatal): {e}")

        record["updated_at"] = now_ict().strftime("%Y-%m-%d %H:%M")
        log.info(
            f"✅ Context refreshed — "
            f"regime={record['market_regime']} "
            f"close={record['vnindex_close']} "
            f"chg_1d={record.get('vnindex_chg_1d')}%"
        )
    else:
        # API fail → chỉ bump updated_at, giữ nguyên data cũ
        record["updated_at"] = now_ict().strftime("%Y-%m-%d %H:%M")
        log.warning(
            "⚠️ VNINDEX trend fetch failed — "
            "giữ nguyên data cũ, chỉ bump updated_at"
        )

    # 3. Ghi lại cả 2 path (alias)
    output = [record]
    save_json("market/context.json", output)
    save_json("context.json",        output)

    try:
        import pandas as pd
        save_csv("market/context.csv", pd.DataFrame(output))
        save_csv("context.csv",        pd.DataFrame(output))
    except Exception as e:
        log.warning(f"CSV save failed (non-fatal): {e}")

    log.info("=== CONTEXT REFRESH DONE ===")
