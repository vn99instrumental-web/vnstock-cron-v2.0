"""
bt_data.py — Data layer cho backtest
======================================
ISOLATION:
  ✗ Không import utils/, steps/, config.py
  ✓ Đọc output/finance/cache.json (read-only) để lấy universe
  ✓ Fetch OHLCV từ VCI — cùng source với production
  ✓ Tính TA bằng vnstock_ta — cùng thư viện với production
  ✓ Lưu dataset vào backtest_output/ (không đụng output/)

Run standalone:
  python backtest/bt_data.py
  python backtest/bt_data.py --max 20   # test nhanh với 20 symbols
"""
import os
import sys
import json
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

# Thêm repo root vào path để import vnstock_data
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backtest.bt_config import (
    PROD_OUTPUT, BT_OUTPUT_DIR,
    START_DATE, MIN_HISTORY, HORIZONS, RET_THRESHOLD,
    API_DELAY, MAX_WORKERS,
)

# ── Logging ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ICT = timezone(timedelta(hours=7))


# ══════════════════════════════════════════════════════════════════════
# UNIVERSE — đọc từ finance cache (read-only)
# ══════════════════════════════════════════════════════════════════════

def load_universe(min_pe: bool = True) -> list[str]:
    """
    Lấy danh sách symbols từ output/finance/cache.json.
    Chỉ đọc, không ghi. Filter symbols có data thật (có PE).
    """
    cache_path = PROD_OUTPUT / "finance" / "cache.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"Finance cache không tìm thấy: {cache_path}\n"
            "Chạy cron_daily trước để có dữ liệu."
        )

    with open(cache_path, encoding="utf-8") as f:
        raw = json.load(f)

    # Handle cả 2 format: {symbols: {...}} và {...} flat
    symbols_dict = raw.get("symbols", raw) if isinstance(raw, dict) else {}

    universe = []
    skipped_non_stock = 0
    skipped_no_data   = 0

    for sym, entry in symbols_dict.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("non_stock"):
            skipped_non_stock += 1
            continue
        if min_pe and entry.get("ratio", {}).get("pe") is None:
            skipped_no_data += 1
            continue
        universe.append(sym)

    log.info(
        f"Universe: {len(universe)} symbols "
        f"(skipped: {skipped_non_stock} non-stock, "
        f"{skipped_no_data} no data)"
    )
    return sorted(universe)


# ══════════════════════════════════════════════════════════════════════
# FETCH OHLCV
# ══════════════════════════════════════════════════════════════════════

def today_ict() -> str:
    return datetime.now(ICT).strftime("%Y-%m-%d")


def fetch_ohlcv(symbol: str) -> pd.DataFrame | None:
    """
    Fetch daily OHLCV từ VCI — cùng source với step_snapshot.py.
    Trả None nếu không đủ history.
    """
    try:
        from vnstock_data import Quote
        df = Quote(source="VCI", symbol=symbol).history(
            start=START_DATE,
            end=today_ict(),
            interval="1D",
        )
        if df is None or df.empty:
            return None

        df = df.sort_values("time").reset_index(drop=True)
        df["time"] = pd.to_datetime(df["time"])

        # Rename columns nếu cần (VCI có thể trả volume/vol)
        rename = {}
        for col in df.columns:
            if col.lower() in ("vol", "volume"):
                rename[col] = "volume"
            if col.lower() in ("open", "high", "low", "close"):
                rename[col] = col.lower()
        if rename:
            df = df.rename(columns=rename)

        # Cần ít nhất MIN_HISTORY ngày
        if len(df) < MIN_HISTORY:
            log.debug(f"  {symbol}: chỉ có {len(df)} ngày (cần {MIN_HISTORY})")
            return None

        return df

    except Exception as e:
        log.warning(f"  {symbol}: fetch lỗi — {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
# COMPUTE TA — cùng logic với step_snapshot.py
# ══════════════════════════════════════════════════════════════════════

def compute_ta(df: pd.DataFrame, symbol: str = "") -> pd.DataFrame:
    """
    Tính indicators bằng vnstock_ta — cùng thư viện production.
    Mỗi ngày chỉ thấy data ≤ ngày đó (rolling window, không look-ahead).
    """
    try:
        from vnstock_ta import Indicator  # noqa: F401 — verify import trước
    except ImportError as e:
        raise ImportError(
            f"vnstock_ta không available trong Python environment hiện tại.\n"
            f"Trên GitHub Actions: dùng 'source /opt/vnstock/.venv/bin/activate' trước.\n"
            f"Chi tiết: {e}"
        )

    try:
        df = df.copy()
        ta = Indicator(data=df)

        # ── Trend ──────────────────────────────────────────────────────
        # ema() trả Series full length
        df["ema20"]  = ta.trend.ema(length=20)
        df["ema50"]  = ta.trend.ema(length=50)
        df["ema200"] = ta.trend.ema(length=200)

        # adx() trả DataFrame: ADX_14, ADXR_14_2, DMP_14, DMN_14
        adx_df = ta.trend.adx(length=14)
        df["adx"] = adx_df["ADX_14"] if "ADX_14" in adx_df.columns else np.nan

        # supertrend() trả DataFrame: SUPERT_10_3.0 (line), SUPERTd_10_3.0 (direction)
        # SUPERTd = +1 (bullish) / -1 (bearish) → dùng trực tiếp
        st_df = ta.trend.supertrend(length=10, multiplier=3.0)
        st_dir_col = [c for c in st_df.columns if c.startswith("SUPERTd")]
        df["supertrend_dir"] = st_df[st_dir_col[0]] if st_dir_col else np.nan

        # ── Momentum ───────────────────────────────────────────────────
        df["rsi"] = ta.momentum.rsi(length=14)

        # macd() trả DataFrame: MACD_12_26_9, MACDh_12_26_9 (hist), MACDs_12_26_9
        macd_df = ta.momentum.macd(fast=12, slow=26, signal=9)
        hist_col = [c for c in macd_df.columns if c.startswith("MACDh")]
        df["macd_hist"] = macd_df[hist_col[0]] if hist_col else np.nan

        # stoch() trả DataFrame: STOCHk_14_3_3, STOCHd_14_3_3, STOCHh_14_3_3
        stoch_df = ta.momentum.stoch(k=14, d=3, smooth_k=3)
        k_col = [c for c in stoch_df.columns if c.startswith("STOCHk")]
        d_col = [c for c in stoch_df.columns if c.startswith("STOCHd")]
        df["stoch_k"] = stoch_df[k_col[0]] if k_col else np.nan
        df["stoch_d"] = stoch_df[d_col[0]] if d_col else np.nan

        # ── Volatility ─────────────────────────────────────────────────
        # bbands() trả DataFrame: BBL/BBM/BBU/BBB/BBP. BBP = position (0-1) sẵn!
        bb_df = ta.volatility.bbands(length=20, std=2.0)
        bbp_col = [c for c in bb_df.columns if c.startswith("BBP")]
        df["bb_pos"] = bb_df[bbp_col[0]] if bbp_col else np.nan

        # atr() trả Series
        df["atr"]     = ta.volatility.atr(length=14)
        df["atr_pct"] = df["atr"] / df["close"] * 100

        # ── Volume ─────────────────────────────────────────────────────
        # obv/cmf/mfi trả Series
        df["obv"] = ta.volume.obv()
        df["cmf"] = ta.volume.cmf(length=20)
        df["mfi"] = ta.volume.mfi(length=14)

        # OBV trend: so với EMA của chính OBV (production logic: OBV vs direction)
        df["obv_ema"]   = df["obv"].ewm(span=20, adjust=False).mean()
        df["obv_trend"] = (df["obv"] > df["obv_ema"]).astype(int) * 2 - 1  # +1/-1

        df["vol_ma20"]  = df["volume"].rolling(20).mean()
        df["vol_ratio"] = df["volume"] / df["vol_ma20"].replace(0, np.nan)

    except Exception as e:
        log.warning(f"  {symbol}: TA computation error — {e}")
        import traceback
        log.debug(traceback.format_exc())

    return df


# ══════════════════════════════════════════════════════════════════════
# FORWARD RETURN LABELS
# ══════════════════════════════════════════════════════════════════════

def add_forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Với mỗi ngày t, tính return sau N ngày giao dịch.
    Ngày cuối (thiếu forward data) → NaN.
    label: +1 (UP) | -1 (DOWN) | 0 (FLAT, trong ±RET_THRESHOLD)
    """
    closes = df["close"].values
    n      = len(closes)

    for h in HORIZONS:
        fwd_ret   = np.full(n, np.nan)
        fwd_label = np.full(n, np.nan)

        for i in range(n - h):
            if closes[i] and closes[i] > 0:
                ret          = (closes[i + h] - closes[i]) / closes[i]
                fwd_ret[i]   = ret
                fwd_label[i] = (
                     1 if ret >  RET_THRESHOLD else
                    -1 if ret < -RET_THRESHOLD else
                     0
                )

        df[f"ret_{h}d"]   = fwd_ret
        df[f"label_{h}d"] = fwd_label

    return df


# ══════════════════════════════════════════════════════════════════════
# SCORE TECHNICAL — chỉ 4 groups có thể replay sạch
# ══════════════════════════════════════════════════════════════════════

def score_technical_raw(row: pd.Series) -> dict:
    """
    Tính raw score (TRƯỚC khi cap) cho 4 technical groups.
    Lưu cả raw lẫn capped để grid search có thể replay với caps mới.

    Mirrors step_scoring.py logic chính xác — không tự sáng tạo.
    """
    from backtest.bt_config import CURRENT_CAPS, CURRENT_WEIGHTS

    s = {"trend": 0, "momentum": 0, "volume": 0, "volatility": 0}

    atr_pct   = float(row.get("atr_pct") or 0)
    flat      = atr_pct < 0.5
    w         = 0.5 if flat else 1.0

    price     = float(row.get("close") or 0)
    ema20     = row.get("ema20")
    ema50     = row.get("ema50")
    ema200    = row.get("ema200")
    adx       = row.get("adx")
    st_dir    = row.get("supertrend_dir")   # +1 bullish / -1 bearish (SUPERTd)
    rsi       = row.get("rsi")
    macd_hist = row.get("macd_hist")
    stoch_k   = row.get("stoch_k")
    stoch_d   = row.get("stoch_d")
    cmf       = row.get("cmf")
    mfi       = row.get("mfi")
    obv_trend = row.get("obv_trend")         # +1 / -1 (OBV vs EMA20 của OBV)
    vol_ratio = row.get("vol_ratio")
    bb_pos    = row.get("bb_pos")

    W = CURRENT_WEIGHTS

    # ── Trend ──────────────────────────────────────────────────────────
    if ema20 and ema50:
        pts = W["trend"]["ema_cross"] if ema20 > ema50 else -W["trend"]["ema_cross"]
        s["trend"] += round(pts * w)

    if price and ema200:
        pts = W["trend"]["price_ema200"]
        s["trend"] += pts if price > ema200 else -pts
    elif price and ema20:
        s["trend"] += 3 if price > ema20 else -3   # fallback

    if adx:
        if adx > 25:
            s["trend"] += W["trend"]["adx_strong"]
        # adx < 20 → +0 (sideways, không penalize)

    if st_dir is not None and not pd.isna(st_dir):
        # SUPERTd_10_3.0: +1 = uptrend (bullish), -1 = downtrend (bearish)
        try:
            if float(st_dir) > 0:
                s["trend"] += W["trend"]["supertrend"]
            else:
                s["trend"] -= W["trend"]["supertrend"]
        except (TypeError, ValueError):
            pass

    # ── Momentum ───────────────────────────────────────────────────────
    if rsi:
        rsi = float(rsi)
        if rsi < 30:
            s["momentum"] += W["momentum"]["rsi_oversold"]
        elif rsi > 70:
            s["momentum"] += W["momentum"]["rsi_overbought"]   # negative
        elif 40 <= rsi <= 60:
            s["momentum"] += W["momentum"]["rsi_neutral"]

    if macd_hist is not None:
        pts = W["momentum"]["macd_hist"] if float(macd_hist) > 0 else -W["momentum"]["macd_hist"]
        s["momentum"] += round(pts * w)

    if stoch_k is not None:
        k = float(stoch_k)
        if k < 20:
            s["momentum"] += W["momentum"]["stoch_zone"]
        elif k > 80:
            s["momentum"] -= W["momentum"]["stoch_zone"]
        if stoch_d is not None:
            d = float(stoch_d)
            if k > d and k < 80:
                s["momentum"] += W["momentum"]["stoch_cross"]
            elif k < d and k > 20:
                s["momentum"] -= W["momentum"]["stoch_cross"]

    # ── Volume ─────────────────────────────────────────────────────────
    if cmf is not None:
        c = float(cmf)
        if c > 0.1:    s["volume"] += W["volume"]["cmf_strong"]
        elif c < -0.1: s["volume"] -= W["volume"]["cmf_strong"]
        elif c > 0:    s["volume"] += W["volume"]["cmf_weak"]
        else:          s["volume"] -= W["volume"]["cmf_weak"]

    if mfi is not None:
        m = float(mfi)
        if m > 60:   s["volume"] += W["volume"]["mfi_high"]
        elif m < 40: s["volume"] += W["volume"]["mfi_low"]   # negative

    if obv_trend is not None and not pd.isna(obv_trend):
        # obv_trend = +1 (OBV > EMA20 của OBV) / -1 — tính sẵn trong compute_ta
        try:
            s["volume"] += W["volume"]["obv_trend"] if float(obv_trend) > 0 else -W["volume"]["obv_trend"]
        except (TypeError, ValueError):
            pass

    if vol_ratio is not None:
        vr = float(vol_ratio)
        if vr > 2.0:   s["volume"] += W["volume"]["vol_ratio_2x"]
        elif vr > 1.5: s["volume"] += W["volume"]["vol_ratio_1_5x"]
        elif vr < 0.5: s["volume"] += W["volume"]["vol_ratio_low"]

    # ── Volatility (BB) ────────────────────────────────────────────────
    if bb_pos is not None:
        b = float(bb_pos)
        W_v = W["volatility"]
        if b > 0.8:       s["volatility"] += W_v["bb_upper"]    # negative
        elif b < 0.2:     s["volatility"] += W_v["bb_lower"]    # positive
        elif b > 0.5:     s["volatility"] += W_v["bb_mid_up"]
        else:             s["volatility"] += W_v["bb_mid_down"]

    # ── Build output: raw + capped ─────────────────────────────────────
    result = {}
    for g, raw in s.items():
        cap               = CURRENT_CAPS[g]
        result[f"{g}_raw"]   = raw
        result[f"{g}_capped"] = max(-cap, min(cap, raw))

    result["tech_score_current"] = sum(
        result[f"{g}_capped"] for g in s
    )
    result["flat_market"] = flat
    return result


# ══════════════════════════════════════════════════════════════════════
# PROCESS ONE SYMBOL
# ══════════════════════════════════════════════════════════════════════

def process_symbol(symbol: str) -> pd.DataFrame | None:
    """Fetch + TA + labels + scoring cho 1 symbol. Thread-safe."""
    df = fetch_ohlcv(symbol)
    if df is None:
        return None

    df = compute_ta(df, symbol)
    df = add_forward_returns(df)

    # Chỉ giữ các ngày có đủ TA (sau warmup EMA200)
    df = df.dropna(subset=["ema200", "rsi"]).copy()
    if len(df) < 20:
        return None

    # Score mỗi ngày
    score_rows = df.apply(score_technical_raw, axis=1)
    df_scores  = pd.DataFrame(score_rows.tolist(), index=df.index)

    # Ghép lại — chỉ giữ cột cần thiết
    keep_cols = [
        "time", "open", "high", "low", "close", "volume",
        "atr_pct", "vol_ratio",
        # Labels
        *[f"ret_{h}d" for h in HORIZONS],
        *[f"label_{h}d" for h in HORIZONS],
        # TA raw (để debug)
        "ema20", "ema50", "ema200", "adx", "supertrend_dir", "rsi",
        "macd_hist", "stoch_k", "stoch_d",
        "cmf", "mfi", "obv", "obv_trend", "bb_pos",
    ]
    keep_cols = [c for c in keep_cols if c in df.columns]
    df_out    = pd.concat([df[keep_cols], df_scores], axis=1)
    df_out.insert(0, "symbol", symbol)

    return df_out


# ══════════════════════════════════════════════════════════════════════
# MAIN — BUILD DATASET
# ══════════════════════════════════════════════════════════════════════

def build_dataset(max_symbols: int | None = None) -> pd.DataFrame:
    """
    Build historical dataset cho tất cả symbols trong universe.
    Output: backtest_output/dataset.parquet

    Không đụng output/ ngoài việc đọc finance/cache.json.
    """
    BT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = BT_OUTPUT_DIR / "dataset.parquet"

    # ── Verify dependencies trước khi fetch bất cứ thứ gì ─────────────
    try:
        from vnstock_ta import Indicator  # noqa: F401
        log.info("vnstock_ta.Indicator: OK")
    except ImportError:
        log.error(
            "vnstock_ta.Indicator không available!\n"
            "Đảm bảo chạy trong venv: source /opt/vnstock/.venv/bin/activate"
        )
        return pd.DataFrame()

    try:
        import pandas as pd  # noqa: F401
        import pyarrow  # noqa: F401
        log.info("pandas + pyarrow: OK")
    except ImportError as e:
        log.error(f"Missing dependency: {e}")
        return pd.DataFrame()

    symbols = load_universe()
    if max_symbols:
        symbols = symbols[:max_symbols]
        log.info(f"Limited to {max_symbols} symbols (test mode)")

    log.info(f"Processing {len(symbols)} symbols (workers={MAX_WORKERS})...")

    all_frames: list[pd.DataFrame] = []
    ok_count   = 0
    err_count  = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(process_symbol, sym): sym
            for sym in symbols
        }
        for i, future in enumerate(as_completed(future_map), 1):
            sym = future_map[future]
            try:
                result = future.result()
                if result is not None and len(result) > 0:
                    all_frames.append(result)
                    ok_count += 1
                    log.info(f"  [{i}/{len(symbols)}] ✓ {sym}: {len(result)} rows")
                else:
                    err_count += 1
                    log.info(f"  [{i}/{len(symbols)}] ⊘ {sym}: skip (no data)")
            except Exception as e:
                err_count += 1
                log.warning(f"  [{i}/{len(symbols)}] ✗ {sym}: {e}")

            time.sleep(API_DELAY)

    if not all_frames:
        log.error("Không có data nào! Kiểm tra kết nối VCI.")
        return pd.DataFrame()

    dataset = pd.concat(all_frames, ignore_index=True)
    dataset["time"] = pd.to_datetime(dataset["time"])

    # Save
    dataset.to_parquet(output_path, index=False)
    log.info(f"\n{'='*60}")
    log.info(f"Dataset saved: {output_path}")
    log.info(f"  Rows    : {len(dataset):,}")
    log.info(f"  Symbols : {dataset['symbol'].nunique()} / {len(symbols)}")
    log.info(f"  Date    : {dataset['time'].min().date()} → {dataset['time'].max().date()}")
    log.info(f"  OK/Err  : {ok_count}/{err_count}")

    # Label distribution
    for h in HORIZONS:
        col     = f"label_{h}d"
        counts  = dataset[col].value_counts().sort_index()
        total   = counts.sum()
        dist    = {int(k): f"{v} ({v/total:.1%})" for k, v in counts.items()}
        log.info(f"  label_{h}d: {dist}")

    return dataset


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build backtest dataset")
    parser.add_argument("--max", type=int, default=None,
                        help="Giới hạn số symbols (test mode)")
    args = parser.parse_args()
    build_dataset(max_symbols=args.max)
