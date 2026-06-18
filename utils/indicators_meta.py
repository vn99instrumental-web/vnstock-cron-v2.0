"""
utils/indicators_meta.py — Metadata cho mọi field trong signals_display.csv
=============================================================================
4 header rows của signals_display.csv:
  Row 1: field name
  Row 2: desc
  Row 3: formula
  Row 4: baseline

CHANGELOG:
  2026-05-27 — Phase 1+2 additions:
    NEW fields: ema200, price_vs_ema200_pct, vol_ma_ratio, vol_today, vol_avg_20d,
                bs_debt_to_equity, is_rev_growth_yoy, is_profit_growth_yoy,
                volatility_score, order_flow_score, confluence_bonus,
                tech_score, fund_score, confidence, pattern_flags
    UPDATED: news_score (±5 symmetric), total_score (new thresholds 80/40/-15/-40),
             fundamental_score (cap ±20, includes D/E), growth_score (YoY preferred),
             volume_score (includes vol_ma_ratio), news_industry/mention/macro (centered)
"""

# ── Unit constants ─────────────────────────────────────────────────────────────
_UNIT_NONE        = ""
_UNIT_PRICE       = "VND"
_UNIT_PCT_DEC     = "%"
_UNIT_VOL         = "CP"
_UNIT_SCORE       = "điểm"
_UNIT_KBS_MONEY   = "tỷ VND"   # các field KBS money (÷1e9)
_UNIT_FF_MONEY    = "VND"       # FF dùng đơn vị gốc
_UNIT_TY_VND_DAY  = "tỷ VND/ngày"


def get_indicator_unit(field: str) -> str:
    """
    Trả về unit string cho 1 field. Dùng trong formatter / display layer.
    Khi đổi source → chỉ cần cập nhật _UNIT_KBS_MONEY hoặc _UNIT_FF_MONEY.
    """
    try:
        from utils.formatter import MONEY_COLS_MIL, MONEY_COLS_VND
        if field in MONEY_COLS_MIL:
            return _UNIT_KBS_MONEY
        if field in MONEY_COLS_VND:
            return _UNIT_FF_MONEY
    except ImportError:
        pass

    meta = INDICATORS_META.get(field, {})
    return meta.get("unit", _UNIT_NONE)


# ── Main metadata dict ────────────────────────────────────────────────────────
INDICATORS_META = {

    # ══════════════════════════════════════════════════════════════
    # PRIMARY KEYS
    # ══════════════════════════════════════════════════════════════
    "symbol"         : {"desc": "Mã cổ phiếu",            "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "group"          : {"desc": "Nhóm tăng/giảm",          "formula": "-",                           "baseline": "GAINER/LOSER",                                   "unit": _UNIT_NONE},
    "industry"       : {"desc": "Ngành ICB",                "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "icb_code"       : {"desc": "Mã ICB ngành",             "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "time"           : {"desc": "Thời gian cập nhật",       "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "date"           : {"desc": "Ngày giao dịch",           "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "exchange"       : {"desc": "Sàn giao dịch",            "formula": "-",                           "baseline": "HSX/HNX/UPCOM",                                  "unit": _UNIT_NONE},

    # ══════════════════════════════════════════════════════════════
    # SNAPSHOT
    # ══════════════════════════════════════════════════════════════
    "price"          : {"desc": "Giá hiện tại",             "formula": "last_price",                  "baseline": "-",                                              "unit": _UNIT_PRICE},
    "price_type"     : {"desc": "Loại giá",                 "formula": "-",                           "baseline": "realtime/last_close",                            "unit": _UNIT_NONE},
    "price_date"     : {"desc": "Ngày giá",                 "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "snap_time"      : {"desc": "Giờ snapshot",             "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "intra_buy_vol"  : {"desc": "KL mua chủ động",          "formula": "Σ vol match_type=Buy",        "baseline": "Cao = áp lực mua",                               "unit": _UNIT_VOL},
    "intra_sell_vol" : {"desc": "KL bán chủ động",          "formula": "Σ vol match_type=Sell",       "baseline": "Cao = áp lực bán",                               "unit": _UNIT_VOL},
    "intra_delta"    : {"desc": "Chênh lệch mua-bán",       "formula": "buy_vol - sell_vol",          "baseline": ">0 mua nhiều hơn",                               "unit": _UNIT_VOL},
    "intra_buy_ratio": {"desc": "Tỷ lệ mua chủ động",      "formula": "buy_vol/(buy+sell)",          "baseline": ">0.6 mua mạnh",                                  "unit": _UNIT_PCT_DEC},
    "depth_buy"      : {"desc": "KL chờ mua (depth)",       "formula": "Σ buy_volume depth",          "baseline": "Cao = nhu cầu mua",                              "unit": _UNIT_VOL},
    "depth_sell"     : {"desc": "KL chờ bán (depth)",       "formula": "Σ sell_volume depth",         "baseline": "Cao = áp lực bán",                               "unit": _UNIT_VOL},
    "depth_buy_ratio": {"desc": "Tỷ lệ mua/tổng depth",    "formula": "depth_buy/(buy+sell)",        "baseline": ">0.6 thiên mua",                                 "unit": _UNIT_PCT_DEC},

    # ══════════════════════════════════════════════════════════════
    # RANKING
    # ══════════════════════════════════════════════════════════════
    "last_price"               : {"desc": "Giá đóng cửa",           "formula": "-",                           "baseline": "-",                                   "unit": _UNIT_PRICE},
    "price_change_1d"          : {"desc": "Thay đổi giá tuyệt đối", "formula": "price - prev_close",          "baseline": "-",                                   "unit": _UNIT_PRICE},
    "price_change_pct_1d"      : {"desc": "% thay đổi giá",         "formula": "(price-prev)/prev×100",       "baseline": ">0 tăng <0 giảm",                     "unit": _UNIT_PCT_DEC},
    "accumulated_value"        : {"desc": "Giá trị GD tích lũy",    "formula": "Σ(price×vol)",                "baseline": ">5 tỷ thanh khoản tốt",               "unit": _UNIT_FF_MONEY},
    "volume_spike_20d_pct"     : {"desc": "Volume đột biến vs 20D", "formula": "vol/avg_vol_20d×100",         "baseline": ">200% đột biến mạnh",                 "unit": _UNIT_PCT_DEC},
    "deal_volume_spike_20d_pct": {"desc": "Đột biến thỏa thuận",    "formula": "deal_vol/avg×100",            "baseline": ">100% có tổ chức vào",                "unit": _UNIT_PCT_DEC},

    # ══════════════════════════════════════════════════════════════
    # TA — TREND
    # ══════════════════════════════════════════════════════════════
    "ema20"              : {"desc": "EMA 20 ngày",                 "formula": "EMA(close,20)",               "baseline": "EMA20>EMA50 = bullish +15đ(×0.5 flat)",          "unit": _UNIT_PRICE},
    "ema50"              : {"desc": "EMA 50 ngày",                 "formula": "EMA(close,50)",               "baseline": "EMA20>EMA50 = bullish cross",                     "unit": _UNIT_PRICE},
    # Phase 2.7 NEW — major long-term support/resistance
    "ema200"             : {"desc": "EMA 200 ngày",                "formula": "EMA(close,200)",              "baseline": "Price>EMA200 = long-term bullish +5đ | Price<EMA200 -5đ. Tính từ 12M history. Fallback dùng EMA20 ±3đ nếu <200 ngày.", "unit": _UNIT_PRICE},
    "ema_cross_pct"      : {"desc": "% EMA20 vs EMA50",            "formula": "(EMA20-EMA50)/EMA50×100",     "baseline": ">0 bullish <0 bearish",                          "unit": _UNIT_PCT_DEC},
    "price_vs_ema20_pct" : {"desc": "% giá vs EMA20",              "formula": "(price-EMA20)/EMA20×100",     "baseline": ">0 trên EMA20",                                  "unit": _UNIT_PCT_DEC},
    # Phase 2.7 NEW
    "price_vs_ema200_pct": {"desc": "% giá vs EMA200",             "formula": "(price-EMA200)/EMA200×100",   "baseline": ">0 trên EMA200 (uptrend dài hạn) | <0 dưới EMA200", "unit": _UNIT_PCT_DEC},
    "adx"                : {"desc": "Sức mạnh xu hướng",           "formula": "ADX(14)",                     "baseline": ">25 mạnh +5đ | <20 sideways 0đ",                 "unit": "0–100"},
    "supertrend"         : {"desc": "Supertrend level",            "formula": "ST(10,3)",                    "baseline": "Giá>ST = uptrend +5đ | Giá<ST -5đ",              "unit": _UNIT_PRICE},
    # v2.2 NEW (Hướng A) — library indicators (vnstock_ta)
    "linreg_20"          : {"desc": "Linear Regression 20",         "formula": "linreg(close,20) last value",  "baseline": "Giá projected từ regression 20 phiên. Dùng để tính slope.",                                  "unit": _UNIT_PRICE},
    "linreg_slope_pct"   : {"desc": "% slope linreg 5 phiên",       "formula": "(linreg[t]-linreg[t-5])/|linreg[t-5]|×100", "baseline": ">+3% strong up +3đ | >+1% up +1đ | ±1% flat 0đ | <-1% down -1đ | <-3% strong down -3đ", "unit": _UNIT_PCT_DEC},
    "aroon_osc"          : {"desc": "Aroon Oscillator (14)",        "formula": "Aroon Up - Aroon Down",        "baseline": ">+60 strong up +3đ | >+30 up +2đ | ±30 flat 0đ | <-30 down -2đ | <-60 strong down -3đ.",       "unit": "-100 đến +100"},
    "donchian_upper_prev": {"desc": "Donchian high 20d (PREV bar)", "formula": "max(high[t-21:t-1])",          "baseline": "Price > prev_DCU = breakout +2đ. Dùng prev (không include today) để detect breakout đúng.", "unit": _UNIT_PRICE},
    "donchian_lower_prev": {"desc": "Donchian low 20d (PREV bar)",  "formula": "min(low[t-21:t-1])",           "baseline": "Price < prev_DCL = breakdown -2đ.",                                                          "unit": _UNIT_PRICE},

    # ══════════════════════════════════════════════════════════════
    # TA — MOMENTUM
    # ══════════════════════════════════════════════════════════════
    "rsi"       : {"desc": "Relative Strength Index",              "formula": "RSI(14)",                     "baseline": "<30 oversold +15đ | >70 overbought -10đ | 40-60 neutral +5đ", "unit": "0–100"},
    "macd"      : {"desc": "MACD line",                            "formula": "EMA12-EMA26",                 "baseline": ">0 bullish",                                     "unit": _UNIT_PRICE},
    "macd_sig"  : {"desc": "MACD signal line",                     "formula": "EMA9(MACD)",                  "baseline": "MACD cross up = buy",                            "unit": _UNIT_PRICE},
    "macd_hist" : {"desc": "MACD histogram",                       "formula": "MACD-signal",                 "baseline": ">0 +10đ(×0.5 flat) | <0 -10đ(×0.5 flat)",       "unit": _UNIT_PRICE},
    "stoch_k"   : {"desc": "Stochastic %K",                        "formula": "Stoch(14,3,3).K",             "baseline": "<20 oversold +5đ | >80 overbought -5đ",          "unit": "0–100"},
    "stoch_d"   : {"desc": "Stochastic %D",                        "formula": "Stoch(14,3,3).D",             "baseline": "K>D cross up +3đ | K<D -3đ (ngoài vùng cực đoan)", "unit": "0–100"},
    # v2.2 NEW (Hướng A)
    "willr_14"  : {"desc": "Williams %R (14)",                     "formula": "(highest_high-close)/(HH-LL)×-100", "baseline": "<= -80 oversold +3đ | <= -60 +1đ | mid 0đ | >= -40 -1đ | >= -20 overbought -3đ. Reverse-coded.", "unit": "-100 đến 0"},

    # ══════════════════════════════════════════════════════════════
    # TA — VOLATILITY (BB moved here; ATR/atr_pct dùng làm filter)
    # ══════════════════════════════════════════════════════════════
    "bb_upper"   : {"desc": "Bollinger Band trên",                 "formula": "BB(20,2).upper",              "baseline": "Giá chạm = quá mua",                             "unit": _UNIT_PRICE},
    "bb_mid"     : {"desc": "Bollinger Band giữa",                 "formula": "BB(20,2).mid=SMA20",          "baseline": "Hỗ trợ/kháng cự động",                           "unit": _UNIT_PRICE},
    "bb_lower"   : {"desc": "Bollinger Band dưới",                 "formula": "BB(20,2).lower",              "baseline": "Giá chạm = quá bán",                             "unit": _UNIT_PRICE},
    "bb_position": {"desc": "Vị trí giá trong BB",                 "formula": "(price-lower)/(upper-lower)", "baseline": "<0.2 oversold +5đ (volatility group) | >0.8 overbought -5đ. Phase 2.9: đã chuyển về volatility_score.", "unit": "0–1"},
    "atr"        : {"desc": "Average True Range",                  "formula": "ATR(14)",                     "baseline": "Cao = biến động lớn",                            "unit": _UNIT_PRICE},
    "atr_pct"    : {"desc": "ATR% biến động tương đối",            "formula": "ATR(14)/price×100",           "baseline": "<0.5% flat (EMA/MACD weight×0.5) | >1.5% biến động mạnh", "unit": _UNIT_PCT_DEC},

    # ══════════════════════════════════════════════════════════════
    # TA — VOLUME
    # ══════════════════════════════════════════════════════════════
    "obv"          : {"desc": "On Balance Volume",                 "formula": "Σ±volume theo giá",           "baseline": "OBV & EMA cùng chiều +4đ | divergence -4đ",      "unit": _UNIT_VOL},
    "cmf"          : {"desc": "Chaikin Money Flow",                "formula": "CMF(20)",                     "baseline": ">0.1 inflow +8đ | <-0.1 outflow -8đ",            "unit": "-1 đến 1"},
    "mfi"          : {"desc": "Money Flow Index",                  "formula": "MFI(14)",                     "baseline": "<20 oversold +8đ | >80 overbought -5đ",          "unit": "0–100"},
    # v2.2 NEW (Hướng A) — library indicators
    "ad_line"          : {"desc": "Accumulation/Distribution Line", "formula": "Σ((close-low)-(high-close))/(high-low)×volume", "baseline": "Cumulative money flow. Slope dương = accumulation. Dùng ad_slope_20d_pct để score.", "unit": _UNIT_VOL},
    "ad_slope_20d_pct" : {"desc": "% slope A/D Line 20 phiên",     "formula": "(AD[t]-AD[t-20])/|AD[t-20]|×100", "baseline": ">+5% strong accum +2đ | >+1% +1đ | ±1% 0đ | <-1% -1đ | <-5% strong dist -2đ.",       "unit": _UNIT_PCT_DEC},
    "efi_13"           : {"desc": "Elder Force Index (13)",         "formula": "EMA13((close-prev_close)×volume)", "baseline": "Dấu = hướng áp lực; magnitude/vol_today để chuẩn hóa. Strength>2.0 ±3đ | >0.5 ±2đ | else ±1đ.", "unit": _UNIT_VOL},
    # Phase 2.8 NEW — breakout confirmation
    "vol_ma_ratio" : {"desc": "Volume hôm nay / TB20 ngày",        "formula": "vol_today / avg_vol_20d",     "baseline": ">2.0 breakout +5đ | >1.5 elevated +3đ | <0.5 yếu -3đ", "unit": "×"},
    "vol_today"    : {"desc": "Volume hôm nay",                    "formula": "volume cuối cùng trong OHLCV","baseline": "-",                                              "unit": _UNIT_VOL},
    "vol_avg_20d"  : {"desc": "Volume TB 20 ngày",                 "formula": "mean(volume, 20 ngày gần)",   "baseline": "Baseline so sánh vol_ma_ratio",                  "unit": _UNIT_VOL},

    # ══════════════════════════════════════════════════════════════
    # FOREIGN FLOW
    # ══════════════════════════════════════════════════════════════
    "ff_buy_val_5d"   : {"desc": "FF mua 5 ngày",                  "formula": "Σ fr_buy_val_matched 5d",     "baseline": "Cao = ngoại mua mạnh",                           "unit": _UNIT_FF_MONEY},
    "ff_sell_val_5d"  : {"desc": "FF bán 5 ngày",                  "formula": "Σ fr_sell_val_matched 5d",    "baseline": "Cao = ngoại bán mạnh",                           "unit": _UNIT_FF_MONEY},
    "ff_net_val_5d"   : {"desc": "FF ròng 5 ngày",                 "formula": "buy-sell 5d",                 "baseline": ">0 mua ròng +5đ | <0 bán ròng -5đ",              "unit": _UNIT_FF_MONEY},
    "ff_net_val_20d"  : {"desc": "FF ròng 20 ngày",                "formula": "buy-sell 20d",                "baseline": ">0 tích lũy +5đ | <0 phân phối -5đ",             "unit": _UNIT_FF_MONEY},
    "ff_room"         : {"desc": "Room ngoại còn lại",             "formula": "fr_current_room",             "baseline": ">0 còn room mua",                                "unit": _UNIT_FF_MONEY},
    "ff_trend"        : {"desc": "Xu hướng FF 20 ngày",            "formula": "slope(ff_net_20d)",           "baseline": ">0 tích lũy dần +5đ | <0 phân phối -5đ",         "unit": _UNIT_TY_VND_DAY},
    "ff_consistency"  : {"desc": "Tỷ lệ ngày FF dương 20D",        "formula": "count(ff_net>0)/20",          "baseline": ">0.6 tích lũy đều | <0.4 bán đều",               "unit": "0–1"},
    "ff_acceleration" : {"desc": "Gia tốc FF",                     "formula": "avg_ff_5d - avg_ff_20d",      "baseline": ">0 tăng tốc mua +5đ | <0 giảm tốc -5đ",         "unit": _UNIT_TY_VND_DAY},
    "ff_data_invalid" : {"desc": "FF data bị wipe",                "formula": "validation gate",             "baseline": "True = CafeF library bug detected",              "unit": _UNIT_NONE},
    "insider_count"   : {"desc": "Số giao dịch insider gần đây",   "formula": "count insider_deal(5)",       "baseline": ">0 có giao dịch nội bộ",                         "unit": "lần"},
    "insider_latest"  : {"desc": "Loại GD insider gần nhất",       "formula": "action_type.iloc[0]",         "baseline": "buy/sell",                                       "unit": _UNIT_NONE},
    "insider_name"    : {"desc": "Tên insider gần nhất",           "formula": "trader_name.iloc[0]",         "baseline": "-",                                              "unit": _UNIT_NONE},

    # ══════════════════════════════════════════════════════════════
    # FINANCE — Ratio (KBS quarterly)
    # ══════════════════════════════════════════════════════════════
    "r_period"      : {"desc": "Kỳ báo cáo ratio",                 "formula": "KBS ratio period",            "baseline": "YYYY-QN",                                        "unit": _UNIT_NONE},
    "r_pe"          : {"desc": "P/E ratio",                        "formula": "pe_ratio (KBS, ~TTM)",        "baseline": "<10 cheap +10đ | 10-15 +7đ | 15-25 +3đ | >25 -5đ | <0 thua lỗ -5đ", "unit": "×"},
    "r_pb"          : {"desc": "P/B ratio",                        "formula": "pb_ratio",                    "baseline": "<1 below book +5đ | 1-2 +3đ | 2-3 0đ | >3 -3đ | <0 equity âm -5đ", "unit": "×"},
    "r_roe"         : {"desc": "Return on Equity (TTM)",           "formula": "roe_trailling",               "baseline": ">20% +5đ | 15-20 +3đ | 10-15 0đ | <5% -3đ",    "unit": _UNIT_PCT_DEC},
    "r_roa"         : {"desc": "Return on Assets (TTM)",           "formula": "roa_trailling",               "baseline": ">10% tốt",                                       "unit": _UNIT_PCT_DEC},
    "r_eps"         : {"desc": "EPS trailing",                     "formula": "trailing_eps",                "baseline": ">0 có lãi",                                      "unit": _UNIT_PRICE},
    "r_bvps"        : {"desc": "Book value per share",             "formula": "book_value_per_share_bvps",   "baseline": "-",                                              "unit": _UNIT_PRICE},
    "r_beta"        : {"desc": "Beta hệ số rủi ro",                "formula": "beta",                        "baseline": "<1 ít biến động | >1.5 biến động cao",           "unit": "×"},
    "r_div_yield"   : {"desc": "Tỷ suất cổ tức",                   "formula": "dividend_yield",              "baseline": ">5% hấp dẫn",                                    "unit": _UNIT_PCT_DEC},
    "r_gross_margin": {"desc": "Biên lợi nhuận gộp",               "formula": "gross_margin",                "baseline": ">30% tốt",                                       "unit": _UNIT_PCT_DEC},
    "r_net_margin"  : {"desc": "Biên lợi nhuận ròng",              "formula": "net_margin",                  "baseline": ">10% tốt",                                       "unit": _UNIT_PCT_DEC},
    "r_quick_ratio" : {"desc": "Hệ số thanh khoản nhanh",          "formula": "quick_ratio",                 "baseline": ">1 an toàn",                                     "unit": "×"},
    "r_interest_cov": {"desc": "Khả năng trả lãi vay",             "formula": "interest_coverage",           "baseline": ">3 an toàn",                                     "unit": "×"},
    "r_ev_ebitda"   : {"desc": "EV/EBITDA",                        "formula": "ev_ebitda",                   "baseline": "<10 rẻ | >20 đắt",                               "unit": "×"},

    # ══════════════════════════════════════════════════════════════
    # FINANCE — Income Statement (KBS quarterly)
    # ══════════════════════════════════════════════════════════════
    "is_revenue"           : {"desc": "Doanh thu thuần",           "formula": "3_net_revenue (Q)",           "baseline": "-",                                              "unit": _UNIT_KBS_MONEY},
    "is_gross_profit"      : {"desc": "Lợi nhuận gộp",             "formula": "5_gross_profit (Q)",          "baseline": "-",                                              "unit": _UNIT_KBS_MONEY},
    "is_net_profit"        : {"desc": "Lợi nhuận sau thuế",        "formula": "profit_after_tax_shareholders","baseline": ">0 có lãi",                                     "unit": _UNIT_KBS_MONEY},
    "is_operating_profit"  : {"desc": "Lợi nhuận hoạt động",       "formula": "11_operating_profit (Q)",     "baseline": ">0 hoạt động có lãi",                            "unit": _UNIT_KBS_MONEY},
    "is_eps"               : {"desc": "EPS quý",                   "formula": "19_earnings_per_share (Q)",   "baseline": ">0 có lãi/CP",                                   "unit": _UNIT_PRICE},
    "is_rev_growth"        : {"desc": "Tăng trưởng DT QoQ",        "formula": "(rev_Q - rev_Q-1)/|rev_Q-1|", "baseline": ">20% mạnh +5đ | >10% +3đ | >0 +1đ | <-10% -3đ. Ưu tiên YoY nếu có.", "unit": _UNIT_PCT_DEC},
    "is_profit_growth"     : {"desc": "Tăng trưởng LN QoQ",        "formula": "(np_Q - np_Q-1)/|np_Q-1|",   "baseline": ">20% mạnh +5đ | >10% +3đ | >0 +1đ | <-10% -3đ. Ưu tiên YoY nếu có.", "unit": _UNIT_PCT_DEC},
    # Phase 1.1 NEW — YoY preferred over QoQ (less seasonal noise)
    "is_rev_growth_yoy"    : {"desc": "Tăng trưởng DT YoY",        "formula": "(rev_Q - rev_Q-4)/|rev_Q-4|", "baseline": "Loại bỏ seasonal. >20% +5đ | >10% +3đ | >0 +1đ | <-10% -3đ. ĐƯỢC ƯU TIÊN hơn QoQ trong scoring.", "unit": _UNIT_PCT_DEC},
    "is_profit_growth_yoy" : {"desc": "Tăng trưởng LN YoY",        "formula": "(np_Q - np_Q-4)/|np_Q-4|",   "baseline": "Loại bỏ seasonal. >20% +5đ | >10% +3đ | >0 +1đ | <-10% -3đ. ĐƯỢC ƯU TIÊN hơn QoQ trong scoring.", "unit": _UNIT_PCT_DEC},

    # ══════════════════════════════════════════════════════════════
    # FINANCE — Balance Sheet (KBS quarterly)
    # ══════════════════════════════════════════════════════════════
    "bs_total_assets"  : {"desc": "Tổng tài sản",                  "formula": "total_assets (Q)",            "baseline": "-",                                              "unit": _UNIT_KBS_MONEY},
    "bs_equity"        : {"desc": "Vốn chủ sở hữu",               "formula": "owner_s_equity (Q)",          "baseline": ">0 healthy",                                     "unit": _UNIT_KBS_MONEY},
    "bs_total_liab"    : {"desc": "Tổng nợ phải trả",              "formula": "c_liabilities (Q)",           "baseline": "-",                                              "unit": _UNIT_KBS_MONEY},
    "bs_short_debt"    : {"desc": "Nợ vay ngắn hạn",               "formula": "11_short_term_borrowings",    "baseline": "-",                                              "unit": _UNIT_KBS_MONEY},
    "bs_long_debt"     : {"desc": "Nợ vay dài hạn",                "formula": "9_long_term_borrowings",      "baseline": "-",                                              "unit": _UNIT_KBS_MONEY},
    # Phase 1.5 NEW — debt risk indicator
    "bs_debt_to_equity": {"desc": "Tỷ lệ nợ/vốn (D/E)",           "formula": "(total_assets-equity)/equity","baseline": "<0.3 very low +3đ | <1.0 healthy +1đ | <2.0 moderate 0đ | <3.0 high -2đ | ≥3.0 very high -3đ. BỎ QUA cho ngân hàng/bảo hiểm (high D/E là bình thường).", "unit": "×"},

    # ══════════════════════════════════════════════════════════════
    # FINANCE — Cash Flow (KBS annual — KBS quarter format broken)
    # ══════════════════════════════════════════════════════════════
    "cf_operating"    : {"desc": "Dòng tiền hoạt động (năm)",      "formula": "operating_cash_flow (annual)","baseline": ">0 tạo cash thật +5đ | <0 đốt tiền -10đ. SECTOR-AWARE: Banking/Securities/Insurance/RE bỏ qua penalty CFO<0 (business model đặc thù).", "unit": _UNIT_KBS_MONEY},
    "cf_investing"    : {"desc": "Dòng tiền đầu tư (năm)",         "formula": "investing_cash_flow (annual)","baseline": "<0 đang đầu tư (bình thường)",                   "unit": _UNIT_KBS_MONEY},
    "cf_financing"    : {"desc": "Dòng tiền tài chính (năm)",      "formula": "financing_cash_flow (annual)","baseline": "<0 trả nợ/cổ tức (tốt) | >0 huy động vốn",       "unit": _UNIT_KBS_MONEY},
    "cf_free"         : {"desc": "Free Cash Flow (năm)",           "formula": "cf_operating + cf_investing","baseline": ">0 excellent",                                   "unit": _UNIT_KBS_MONEY},
    "cf_quality_ratio": {"desc": "Tỷ lệ CF/LN (cùng năm)",        "formula": "cf_operating_y / net_profit_y","baseline": ">1 +5đ (cash > earnings, quality high) | <0.5 -5đ (earnings without cash). SECTOR-AWARE: bỏ qua cho Banking/Securities/RE/Insurance.", "unit": "×"},

    # ══════════════════════════════════════════════════════════════
    # FINANCE — Precomputed scores (từ step_finance_scan)
    # ══════════════════════════════════════════════════════════════
    "finance_score"        : {"desc": "Tổng điểm tài chính",       "formula": "fundamental+cashflow+growth","baseline": "Max ±38đ",                                        "unit": _UNIT_SCORE},
    "finance_score_fund"   : {"desc": "Điểm fundamental (precomp)","formula": "PE+PB+ROE",                   "baseline": "Max ±18đ",                                        "unit": _UNIT_SCORE},
    "finance_score_cf"     : {"desc": "Điểm CF (precomp)",         "formula": "CFO+CF quality",              "baseline": "Max ±10đ",                                        "unit": _UNIT_SCORE},
    "finance_score_growth" : {"desc": "Điểm growth (precomp)",     "formula": "rev_growth+profit_growth",    "baseline": "Max ±10đ",                                        "unit": _UNIT_SCORE},

    # ══════════════════════════════════════════════════════════════
    # SCORING — Group scores
    # ══════════════════════════════════════════════════════════════
    "market_valuation" : {"desc": "Định giá thị trường",           "formula": "PE VNINDEX percentile 5Y",    "baseline": "CHEAP/FAIR/EXPENSIVE",                           "unit": _UNIT_NONE},
    "trend_score"      : {"desc": "Điểm xu hướng",                 "formula": "EMA cross+EMA200+ADX+ST",     "baseline": "Max ±30đ. Phase 2.7: EMA200 thay Price>EMA20",   "unit": _UNIT_SCORE},
    "momentum_score"   : {"desc": "Điểm đà tăng",                  "formula": "RSI+MACD+Stochastic",         "baseline": "Max ±23đ",                                       "unit": _UNIT_SCORE},
    "volume_score"     : {"desc": "Điểm dòng tiền/volume",         "formula": "CMF+MFI+OBV+VolRatio",        "baseline": "Max ±20đ. Phase 2.8: thêm vol_ma_ratio; Phase 2.9: BB pos → volatility_score", "unit": _UNIT_SCORE},
    # Phase 2.9 NEW GROUP — BB position moved here
    "volatility_score" : {"desc": "Điểm biến động",                "formula": "BB position",                 "baseline": "Max ±5đ. BB pos<0.2 +5đ (oversold) | >0.8 -5đ (overbought). Phase 2.9 tách ra khỏi volume_score.", "unit": _UNIT_SCORE},
    # Phase 1.3 NEW GROUP
    "order_flow_score" : {"desc": "Điểm order flow",               "formula": "pattern + vol_spike×direction","baseline": "Max ±10đ. ACCUMULATION/SPIKE_BUY +5đ | DISTRIBUTION/SPIKE_SELL -5đ | WEAK -3đ. Cần market giờ mở mới có data (intraday=None pre-market).", "unit": _UNIT_SCORE},
    "ff_score"         : {"desc": "Điểm Foreign Flow",             "formula": "FF net5d+net20d+trend+accel", "baseline": "Max ±20đ",                                       "unit": _UNIT_SCORE},
    "fundamental_score": {"desc": "Điểm cơ bản",                   "formula": "PE+PB+ROE+D/E",               "baseline": "Max ±20đ. Phase 1.5: thêm D/E (skip cho ngân hàng/bảo hiểm).", "unit": _UNIT_SCORE},
    "cf_score"         : {"desc": "Điểm chất lượng CF",            "formula": "CFO sign + CF quality ratio", "baseline": "Max ±10đ. Sector-aware: Banking/Securities/RE/Insurance bỏ qua penalty CFO<0.", "unit": _UNIT_SCORE},
    "growth_score"     : {"desc": "Điểm tăng trưởng",              "formula": "rev_growth+profit_growth (YoY preferred)", "baseline": "Max ±10đ. Phase 1.1: ưu tiên YoY (ít seasonal noise) over QoQ.", "unit": _UNIT_SCORE},
    "context_score"    : {"desc": "Điểm context thị trường",       "formula": "market_valuation",            "baseline": "Max ±5đ | CHEAP +5 | EXPENSIVE -5",              "unit": _UNIT_SCORE},
    # Phase 1.2 UPDATED — symmetric ±5
    "news_score"       : {"desc": "Điểm tin tức tổng hợp",         "formula": "industry+mention+macro (centered)", "baseline": "±5đ SYMMETRIC. Phase 1.2: đổi từ 0-10 sang -5..+5. 0=neutral | +5 rất tích cực | -5 rất tiêu cực | Không có tin=0.", "unit": _UNIT_SCORE},
    # Phase 1.6 NEW
    "confluence_bonus" : {"desc": "Thưởng đồng thuận đa nhóm",     "formula": "count(groups > 30% cap threshold)", "baseline": "±10đ. ≥7 nhóm cùng chiều +10 | ≥5 nhóm +5 | ≤5 nhóm âm -5 | ≤7 nhóm âm -10. Threshold = 30% của cap mỗi nhóm.", "unit": _UNIT_SCORE},

    # ══════════════════════════════════════════════════════════════
    # SCORING — Derived subtotals + confidence (Phase 2.10)
    # ══════════════════════════════════════════════════════════════
    # Phase 2.10 NEW
    "tech_score"   : {"desc": "Điểm kỹ thuật tổng hợp",            "formula": "trend+momentum+volume+volatility+order_flow", "baseline": "Phần technical của total_score. Dùng để detect bull-trap: tech_score cao + fund_score thấp = WARNING.", "unit": _UNIT_SCORE},
    "fund_score"   : {"desc": "Điểm cơ bản tổng hợp",              "formula": "fundamental+cf+growth",       "baseline": "Phần fundamental của total_score. fund_score > 0 = healthy business.", "unit": _UNIT_SCORE},

    # ══════════════════════════════════════════════════════════════
    # SCORING — News detail
    # ══════════════════════════════════════════════════════════════
    "news_industry" : {"desc": "Tin tức theo ngành",               "formula": "avg(weighted_sentiment) ngành ICB", "baseline": "Centered ±2đ | 0=neutral. Phase 1.2: từ 0-4/2=neutral sang -2..+2/0=neutral.", "unit": _UNIT_SCORE},
    "news_mention"  : {"desc": "Tin đề cập trực tiếp",             "formula": "avg(weighted_sentiment×1.5) khi symbol in title", "baseline": "Centered ±2đ | 0=neutral | boost 1.5×. Symbol mention từ ticker + tên công ty.", "unit": _UNIT_SCORE},
    "news_macro"    : {"desc": "Tin vĩ mô thị trường",             "formula": "MACRO_KEYWORDS matched × bias", "baseline": "Centered ±1đ | 0=neutral | MACRO_CONTEXT_INDUSTRIES filter. Chỉ áp dụng negative khi article thuộc ngành tài chính/vĩ mô.", "unit": _UNIT_SCORE},
    "news_evidence" : {"desc": "Dẫn chứng tin tức",               "formula": "top 3 articles by |contribution|", "baseline": "[type] source: title (HH:MM) contribution",  "unit": _UNIT_NONE},

    # ══════════════════════════════════════════════════════════════
    # SCORING — Output fields
    # ══════════════════════════════════════════════════════════════
    "total_score"  : {"desc": "Tổng điểm",                         "formula": "Σ(trend+momentum+volume+volatility+order_flow+ff+fund+cf+growth+ctx+news+confluence)", "baseline": "Thresholds v3: ≥80 STRONG BUY | ≥40 BUY | ≥-15 NEUTRAL | ≥-40 SELL | <-40 STRONG SELL. Max ±168 lý thuyết, realistic ±100.", "unit": _UNIT_SCORE},
    "decision"     : {"desc": "Quyết định",                        "formula": "total_score phân loại",        "baseline": "STRONG BUY/BUY/NEUTRAL/SELL/STRONG SELL",        "unit": _UNIT_NONE},
    # Phase 2.10 NEW
    "confidence"   : {"desc": "Độ tin cậy quyết định",             "formula": "tech_score vs fund_score alignment", "baseline": "HIGH = tech+fund cùng hướng mạnh | MEDIUM = trung bình | LOW = mâu thuẫn (BULL_TRAP_RISK, UNCLEAR).", "unit": _UNIT_NONE},
    "pattern_flags": {"desc": "Cờ pattern đặc biệt",               "formula": "tech/fund divergence analysis", "baseline": "CONSENSUS_BULL (T≥30,F≥15) | CONSENSUS_BEAR | BULL_TRAP_RISK (T≥40,F≤-15) | VALUE_OPPORTUNITY (T≤-30,F≥15) | UNCLEAR | [-] = bình thường.", "unit": _UNIT_NONE},
    "signals"      : {"desc": "Chi tiết tín hiệu",                 "formula": "list signals với điểm",        "baseline": "Dạng: SignalName ±Điểm, phân cách | ",           "unit": _UNIT_NONE},
}
