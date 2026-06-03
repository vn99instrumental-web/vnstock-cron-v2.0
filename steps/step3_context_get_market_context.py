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

    chg_5d  = _chg(5)
    chg_20d = _chg(20)

    # ── Phân loại regime ──
    above_50  = close > ema50
    above_200 = (close > ema200) if ema200 is not None else above_50
    c20 = chg_20d if chg_20d is not None else 0.0

    if above_50 and above_200 and c20 > 0:
        regime = "UPTREND"
    elif (not above_50) and (not above_200) and c20 <= -8:
        regime = "DEEP_DOWN"          # giảm sâu — rủi ro hệ thống cao nhất
    elif (not above_50) and (not above_200):
        regime = "DOWNTREND"
    else:
        regime = "SIDEWAYS"

    return {
        "vnindex_close"   : round(close, 2),
        "vnindex_ema50"   : round(ema50, 2),
        "vnindex_ema200"  : round(ema200, 2) if ema200 is not None else None,
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
        "vnindex_chg_5d"   : trend.get("vnindex_chg_5d"),
        "vnindex_chg_20d"  : trend.get("vnindex_chg_20d"),
        "updated_at"       : now_ict().strftime("%Y-%m-%d %H:%M"),
    }
    return [rec]
