"""
bt_config.py — Backtest configuration
======================================
ISOLATION RULES (không được phá vỡ):
  ✗ Không import từ utils/, steps/, config.py của production
  ✗ Không ghi vào output/ (chỉ đọc finance/cache.json để lấy universe)
  ✓ Tất cả output vào BT_OUTPUT_DIR (mặc định: backtest_output/)
  ✓ Chạy local, không qua GitHub Actions
"""
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
# Repo root: 2 cấp trên backtest/
REPO_ROOT      = Path(__file__).parent.parent
PROD_OUTPUT    = REPO_ROOT / "output"           # read-only
BT_OUTPUT_DIR  = REPO_ROOT / "backtest_output"  # write target

# ── Data ───────────────────────────────────────────────────────────────
START_DATE     = "2024-06-01"   # 12M history từ hôm nay
MIN_HISTORY    = 220            # cần EMA200 (200 + buffer 20)
HORIZONS       = [1, 3, 5]     # forward return days
RET_THRESHOLD  = 0.005         # ±0.5% → mới tính là move có nghĩa (0 = flat)

# ── Scoring caps hiện tại (v3 production) ──────────────────────────────
# Thay đổi ở đây để test scenarios khác nhau
CURRENT_CAPS = {
    "trend":      30,
    "momentum":   23,
    "volume":     20,
    "volatility":  5,
}

# ── Internal weights hiện tại (từ step_scoring.py) ─────────────────────
# Dùng để replay chính xác, không tự suy đoán
CURRENT_WEIGHTS = {
    "trend": {
        "ema_cross":     15,   # ×0.5 nếu flat (atr_pct < 0.5)
        "price_ema200":   5,   # fallback price_ema20: ±3
        "adx_strong":     5,   # adx > 25
        "supertrend":     5,   # price vs supertrend
    },
    "momentum": {
        "rsi_oversold":  15,   # rsi < 30
        "rsi_overbought":-10,  # rsi > 70
        "rsi_neutral":    5,   # 40 ≤ rsi ≤ 60
        "macd_hist":     10,   # ×0.5 nếu flat
        "stoch_zone":     5,   # k < 20 or k > 80
        "stoch_cross":    3,   # k vs d cross
    },
    "volume": {
        "cmf_strong":     8,   # |cmf| > 0.1
        "mfi_oversold":   8,   # mfi < 20 → +8 (oversold = bullish)
        "mfi_overbought": -5,  # mfi > 80 → -5 (overbought = bearish)
        "obv_confirm":    4,   # OBV cùng chiều ema_cross → +4, divergence → -4
        "vol_ratio_2x":   5,   # vol_ma_ratio > 2.0 breakout
        "vol_ratio_1_5x": 3,   # vol_ma_ratio > 1.5 elevated
        "vol_ratio_low":  -3,  # vol_ma_ratio < 0.5 weak
    },
    "volatility": {
        "bb_upper":      -5,   # bb_pos > 0.8 (overbought)
        "bb_lower":       5,   # bb_pos < 0.2 (oversold)
        "bb_mid_up":      2,   # 0.5 < bb_pos ≤ 0.8
        "bb_mid_down":   -2,   # 0.2 < bb_pos ≤ 0.5
    },
}

# ── Grid search space ──────────────────────────────────────────────────
# Chạy tất cả combination để tìm caps tốt nhất
CAP_SEARCH_SPACE = {
    "trend":      [20, 25, 30, 35, 40],
    "momentum":   [15, 18, 23, 28],
    "volume":     [10, 15, 20, 25],
    "volatility": [3, 5, 8],
}
# 5×4×4×3 = 240 combos — nhanh (<1 phút)

# Internal weight search (chạy sau khi đã xác định caps)
WEIGHT_SEARCH_SPACE = {
    "trend": {
        "ema_cross":    [10, 12, 15, 18],
        "price_ema200": [3, 5, 8],
        "adx_strong":   [3, 5, 8],
        "supertrend":   [3, 5, 7],
    },
    "momentum": {
        "rsi_oversold":  [10, 12, 15],
        "rsi_overbought": [-12, -10, -8],
        "macd_hist":     [8, 10, 12],
        "stoch_cross":   [2, 3, 5],
    },
}

# ── Evaluation ─────────────────────────────────────────────────────────
MIN_SIGNALS     = 20    # số tối thiểu để tính metric
SCORE_THRESHOLD = 20    # |score| >= threshold mới tính là "có chiều"
API_DELAY       = 0.3   # giây giữa các API calls (rate limit)
MAX_WORKERS     = 5     # concurrent symbol fetches

# ── Thresholds hiện tại (production) ───────────────────────────────────
CURRENT_THRESHOLDS = {
    "strong_buy":  80,
    "buy":         40,
    "neutral_low": -15,
    "sell":        -40,
    # < sell → STRONG SELL
}
