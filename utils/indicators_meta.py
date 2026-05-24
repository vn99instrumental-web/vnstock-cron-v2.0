"""
indicators_meta.py
==================
Mỗi field có 4 attributes: desc, formula, baseline, unit.

unit mô tả đơn vị của GIÁ TRỊ TRONG FILE (sau khi formatter.py xử lý).
Không hardcode unit cho money fields — dùng get_unit() để derive từ formatter.py.
Khi đổi source/formatter → chỉ cần update formatter.py, unit tự động đúng.

Cách dùng:
    from utils.indicators_meta import INDICATORS_META, get_unit
    unit = get_unit('is_revenue')   # → 'tỷ VND (KBS nghìn đồng÷1e6)'
    unit = get_unit('ff_net_val_5d') # → 'tỷ VND (CafeF VND÷1e9)'
    unit = get_unit('rsi')          # → '0–100'

Trong save_display_csv():
    ['unit'] + [get_unit(c) for c in cols]
"""

# ── Unit source labels ────────────────────────────────────────────────────────
# Khi đổi source, chỉ cần đổi label này — không cần sửa từng entry.
_UNIT_KBS_MONEY  = "tỷ VND (KBS ÷1e6)"   # KBS: nghìn đồng → tỷ (÷1e6)
_UNIT_FF_MONEY   = "tỷ VND (CafeF ÷1e9)" # CafeF/VCI: VND → tỷ (÷1e9)
_UNIT_PCT_DEC    = "decimal (0.15=15%)"
_UNIT_PCT_0_100  = "%"
_UNIT_RATIO      = "ratio"
_UNIT_SCORE      = "điểm"
_UNIT_PRICE      = "nghìn VND/cp"         # giá cổ phiếu VN: 72.5 = 72,500 đ
_UNIT_VND_CP     = "VND/cp"               # EPS, BVPS
_UNIT_VOL        = "cổ phiếu"
_UNIT_TY_VND_DAY = "tỷ VND/phiên"
_UNIT_NONE       = "-"


def get_unit(field: str) -> str:
    """
    Derive unit từ formatter.py MONEY_COLS lists + fallback vào INDICATORS_META.
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

    # ── Primary keys ──
    "symbol"         : {"desc": "Mã cổ phiếu",           "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "group"          : {"desc": "Nhóm tăng/giảm",         "formula": "-",                           "baseline": "GAINER/LOSER",                                   "unit": _UNIT_NONE},
    "industry"       : {"desc": "Ngành",                   "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "icb_code"       : {"desc": "Mã ICB ngành",            "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "time"           : {"desc": "Thời gian cập nhật",      "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "date"           : {"desc": "Ngày giao dịch",          "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "exchange"       : {"desc": "Sàn giao dịch",           "formula": "-",                           "baseline": "HSX/HNX/UPCOM",                                  "unit": _UNIT_NONE},

    # ── Snapshot ──
    "price"          : {"desc": "Giá hiện tại",            "formula": "last_price",                  "baseline": "-",                                              "unit": _UNIT_PRICE},
    "price_type"     : {"desc": "Loại giá",                "formula": "-",                           "baseline": "realtime/last_close",                            "unit": _UNIT_NONE},
    "price_date"     : {"desc": "Ngày giá",                "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "snap_time"      : {"desc": "Giờ snapshot",            "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "intra_buy_vol"  : {"desc": "KL mua chủ động",         "formula": "Σ vol match_type=Buy",        "baseline": "Cao = áp lực mua",                               "unit": _UNIT_VOL},
    "intra_sell_vol" : {"desc": "KL bán chủ động",         "formula": "Σ vol match_type=Sell",       "baseline": "Cao = áp lực bán",                               "unit": _UNIT_VOL},
    "intra_delta"    : {"desc": "Chênh lệch mua-bán",      "formula": "buy_vol - sell_vol",          "baseline": ">0 mua nhiều hơn",                               "unit": _UNIT_VOL},
    "intra_buy_ratio": {"desc": "Tỷ lệ mua chủ động",     "formula": "buy_vol/(buy+sell)",          "baseline": ">0.6 mua mạnh",                                  "unit": _UNIT_PCT_DEC},
    "depth_buy"      : {"desc": "KL chờ mua (depth)",      "formula": "Σ buy_volume depth",          "baseline": "Cao = nhu cầu mua",                              "unit": _UNIT_VOL},
    "depth_sell"     : {"desc": "KL chờ bán (depth)",      "formula": "Σ sell_volume depth",         "baseline": "Cao = áp lực bán",                               "unit": _UNIT_VOL},
    "depth_buy_ratio": {"desc": "Tỷ lệ mua/tổng depth",   "formula": "depth_buy/(buy+sell)",        "baseline": ">0.6 thiên mua",                                 "unit": _UNIT_PCT_DEC},

    # ── Ranking ──
    "last_price"              : {"desc": "Giá đóng cửa",          "formula": "-",                           "baseline": "-",                                   "unit": _UNIT_PRICE},
    "price_change_1d"         : {"desc": "Thay đổi giá tuyệt đối","formula": "price - prev_close",          "baseline": "-",                                   "unit": _UNIT_PRICE},
    "price_change_pct_1d"     : {"desc": "% thay đổi giá",        "formula": "(price-prev)/prev×100",       "baseline": ">0 tăng <0 giảm",                     "unit": _UNIT_PCT_DEC},
    "accumulated_value"       : {"desc": "Giá trị GD tích lũy",   "formula": "Σ(price×vol)",                "baseline": ">5 tỷ thanh khoản tốt",               "unit": _UNIT_FF_MONEY},
    "volume_spike_20d_pct"    : {"desc": "Volume đột biến vs 20D","formula": "vol/avg_vol_20d×100",         "baseline": ">200% đột biến mạnh",                 "unit": _UNIT_PCT_DEC},
    "deal_volume_spike_20d_pct": {"desc": "Đột biến thỏa thuận",  "formula": "deal_vol/avg×100",            "baseline": ">100% có tổ chức vào",                "unit": _UNIT_PCT_DEC},

    # ── TA — Trend ──
    "ema20"          : {"desc": "EMA 20 ngày",             "formula": "EMA(close,20)",               "baseline": "Giá>EMA20 = uptrend",                            "unit": _UNIT_PRICE},
    "ema50"          : {"desc": "EMA 50 ngày",             "formula": "EMA(close,50)",               "baseline": "EMA20>EMA50 = bullish",                          "unit": _UNIT_PRICE},
    "ema_cross_pct"  : {"desc": "% EMA20 vs EMA50",        "formula": "(EMA20-EMA50)/EMA50×100",     "baseline": ">0 bullish <0 bearish",                          "unit": _UNIT_PCT_DEC},
    "price_vs_ema20_pct": {"desc": "% giá vs EMA20",       "formula": "(price-EMA20)/EMA20×100",     "baseline": ">0 trên EMA20",                                  "unit": _UNIT_PCT_DEC},
    "adx"            : {"desc": "Sức mạnh xu hướng",       "formula": "ADX(14)",                     "baseline": ">25 mạnh <20 sideways",                          "unit": "0–100"},
    "supertrend"     : {"desc": "Supertrend level",        "formula": "ST(10,3)",                    "baseline": "Giá>ST = uptrend +5đ | Giá<ST -5đ",              "unit": _UNIT_PRICE},

    # ── TA — Momentum ──
    "rsi"            : {"desc": "Relative Strength Index", "formula": "RSI(14)",                     "baseline": "<30 oversold +15đ | >70 overbought -10đ | 40-60 neutral +5đ", "unit": "0–100"},
    "macd"           : {"desc": "MACD line",               "formula": "EMA12-EMA26",                 "baseline": ">0 bullish",                                     "unit": _UNIT_PRICE},
    "macd_sig"       : {"desc": "MACD signal line",        "formula": "EMA9(MACD)",                  "baseline": "MACD cross up = buy",                            "unit": _UNIT_PRICE},
    "macd_hist"      : {"desc": "MACD histogram",          "formula": "MACD-signal",                 "baseline": ">0 +10đ(×0.5 flat) | <0 -10đ(×0.5 flat)",       "unit": _UNIT_PRICE},
    "stoch_k"        : {"desc": "Stochastic %K",           "formula": "Stoch(14,3,3).K",             "baseline": "<20 oversold +5đ | >80 overbought -5đ",          "unit": "0–100"},
    "stoch_d"        : {"desc": "Stochastic %D",           "formula": "Stoch(14,3,3).D",             "baseline": "K>D cross up +3đ | K<D -3đ (ngoài vùng cực đoan)", "unit": "0–100"},

    # ── TA — Volatility ──
    "bb_upper"       : {"desc": "Bollinger Band trên",     "formula": "BB(20,2).upper",              "baseline": "Giá chạm = quá mua",                             "unit": _UNIT_PRICE},
    "bb_mid"         : {"desc": "Bollinger Band giữa",     "formula": "BB(20,2).mid=SMA20",          "baseline": "Hỗ trợ/kháng cự",                               "unit": _UNIT_PRICE},
    "bb_lower"       : {"desc": "Bollinger Band dưới",     "formula": "BB(20,2).lower",              "baseline": "Giá chạm = quá bán",                             "unit": _UNIT_PRICE},
    "bb_position"    : {"desc": "Vị trí giá trong BB",    "formula": "(price-lower)/(upper-lower)",  "baseline": "<0.2 oversold +5đ | >0.8 overbought -5đ | >1 breakout", "unit": "0–1 (>1 breakout)"},
    "atr"            : {"desc": "Average True Range",      "formula": "ATR(14)",                     "baseline": "Cao = biến động lớn",                            "unit": _UNIT_PRICE},
    "atr_pct"        : {"desc": "ATR% biến động tương đối","formula": "ATR(14)/price×100",           "baseline": "<0.5% flat(EMA/MACD×0.5) | >1.5% biến động mạnh", "unit": _UNIT_PCT_DEC},

    # ── TA — Volume ──
    "obv"            : {"desc": "On Balance Volume",       "formula": "Σ±volume theo giá",           "baseline": "OBV & EMA cùng chiều +5đ | divergence -5đ",      "unit": _UNIT_VOL},
    "cmf"            : {"desc": "Chaikin Money Flow",      "formula": "CMF(20)",                     "baseline": ">0.1 inflow +10đ | <-0.1 outflow -10đ",          "unit": "-1 đến 1"},
    "mfi"            : {"desc": "Money Flow Index",        "formula": "MFI(14)",                     "baseline": "<20 oversold +10đ | >80 overbought -5đ",         "unit": "0–100"},

    # ── Foreign Flow ──
    "ff_buy_val_5d"  : {"desc": "FF mua 5 ngày",          "formula": "Σ fr_buy_val_matched 5d",     "baseline": "Cao = ngoại mua mạnh",                           "unit": _UNIT_FF_MONEY},
    "ff_sell_val_5d" : {"desc": "FF bán 5 ngày",          "formula": "Σ fr_sell_val_matched 5d",    "baseline": "Cao = ngoại bán mạnh",                           "unit": _UNIT_FF_MONEY},
    "ff_net_val_5d"  : {"desc": "FF ròng 5 ngày",         "formula": "buy-sell 5d",                 "baseline": ">0 mua ròng +5đ | <0 bán ròng -5đ",              "unit": _UNIT_FF_MONEY},
    "ff_net_val_20d" : {"desc": "FF ròng 20 ngày",        "formula": "buy-sell 20d",                "baseline": ">0 tích lũy +5đ | <0 phân phối -5đ",             "unit": _UNIT_FF_MONEY},
    "ff_room"        : {"desc": "Room ngoại còn lại",     "formula": "fr_current_room",             "baseline": ">0 còn room mua",                                "unit": _UNIT_FF_MONEY},
    "ff_trend"       : {"desc": "Xu hướng FF 20 ngày",    "formula": "slope(ff_net_20d)",           "baseline": ">0 tích lũy dần +5đ | <0 phân phối -5đ",         "unit": _UNIT_TY_VND_DAY},
    "ff_consistency" : {"desc": "Tỷ lệ ngày FF dương",    "formula": "count(ff>0)/20",              "baseline": ">0.6 ngoại mua liên tục",                        "unit": _UNIT_PCT_DEC},
    "ff_acceleration": {"desc": "FF tăng tốc",            "formula": "ff_net_5d_avg vs ff_net_20d_avg", "baseline": ">0 tăng tốc mua +5đ | <0 giảm tốc -5đ",    "unit": _UNIT_TY_VND_DAY},

    # ── Insider ──
    "insider_count"  : {"desc": "Số GD nội bộ gần đây",   "formula": "count insider_deal(5)",       "baseline": "Mua = tin tưởng nội bộ",                         "unit": "lần"},
    "insider_latest" : {"desc": "GD nội bộ gần nhất",     "formula": "action_type.last",            "baseline": "Mua tích cực / Bán tiêu cực",                    "unit": _UNIT_NONE},
    "insider_name"   : {"desc": "Người GD nội bộ",        "formula": "trader_name.last",            "baseline": "-",                                              "unit": _UNIT_NONE},

    # ── Fundamental — Ratio (KBS) ──
    "r_period"       : {"desc": "Kỳ báo cáo",             "formula": "-",                           "baseline": "-",                                              "unit": _UNIT_NONE},
    "r_pe"           : {"desc": "P/E ratio",               "formula": "price/EPS",                   "baseline": "<10 +10đ | <15 +7đ | ≤25 +3đ | >25 -5đ",        "unit": _UNIT_RATIO},
    "r_pb"           : {"desc": "P/B ratio",               "formula": "price/BVPS",                  "baseline": "<1 +5đ | ≤2 +3đ | ≤3 0đ | >3 -3đ",              "unit": _UNIT_RATIO},
    "r_eps"          : {"desc": "Earnings Per Share",      "formula": "net_profit/shares",           "baseline": "Càng cao càng tốt",                              "unit": _UNIT_VND_CP},
    "r_bvps"         : {"desc": "Book Value Per Share",    "formula": "equity/shares",               "baseline": "Cao = tài sản thực nhiều",                       "unit": _UNIT_VND_CP},
    "r_roe"          : {"desc": "Return on Equity",        "formula": "net_profit/equity×100",       "baseline": ">20% +5đ | >15% +3đ | >10% 0đ | <5% -3đ",       "unit": _UNIT_PCT_0_100},
    "r_roa"          : {"desc": "Return on Assets",        "formula": "net_profit/assets×100",       "baseline": ">5% tốt >10% rất tốt",                          "unit": _UNIT_PCT_0_100},
    "r_beta"         : {"desc": "Beta - độ biến động",    "formula": "cov(stock,market)/var(market)","baseline": "<1 ít biến động >1 biến động nhiều",              "unit": _UNIT_RATIO},
    "r_div_yield"    : {"desc": "Tỷ suất cổ tức",         "formula": "dividend/price×100",          "baseline": ">3% hấp dẫn",                                    "unit": _UNIT_PCT_0_100},
    "r_gross_margin" : {"desc": "Biên lợi nhuận gộp",     "formula": "gross_profit/revenue×100",    "baseline": ">30% tốt (tùy ngành)",                          "unit": _UNIT_PCT_0_100},
    "r_net_margin"   : {"desc": "Biên lợi nhuận ròng",    "formula": "net_profit/revenue×100",      "baseline": ">10% tốt (tùy ngành)",                          "unit": _UNIT_PCT_0_100},
    "r_ebit_margin"  : {"desc": "Biên EBIT",               "formula": "EBIT/revenue×100",            "baseline": ">15% tốt",                                       "unit": _UNIT_PCT_0_100},
    "r_quick_ratio"  : {"desc": "Tỷ số thanh khoản",      "formula": "(current-inventory)/current_liab", "baseline": ">1 đủ thanh khoản",                       "unit": _UNIT_RATIO},
    "r_interest_cov" : {"desc": "Khả năng trả lãi vay",   "formula": "EBIT/interest_expense",       "baseline": ">3 an toàn >5 rất tốt",                          "unit": _UNIT_RATIO},
    "r_ev_ebitda"    : {"desc": "EV/EBITDA định giá",      "formula": "EV/EBITDA",                   "baseline": "<10 rẻ | 10-15 hợp lý | >20 đắt",               "unit": _UNIT_RATIO},

    # ── Fundamental — Income Statement (KBS, nghìn đồng → tỷ sau format) ──
    "is_revenue"          : {"desc": "Doanh thu thuần",      "formula": "3_net_revenue Q",             "baseline": "Tăng QoQ tích cực",                         "unit": _UNIT_KBS_MONEY},
    "is_gross_profit"     : {"desc": "Lợi nhuận gộp",       "formula": "5_gross_profit Q",            "baseline": "Tăng = biên gộp tốt",                       "unit": _UNIT_KBS_MONEY},
    "is_net_profit"       : {"desc": "LNST cổ đông CT mẹ",  "formula": "profit_after_tax Q",          "baseline": "Tăng QoQ tích cực",                         "unit": _UNIT_KBS_MONEY},
    "is_operating_profit" : {"desc": "Lợi nhuận HĐ KD",     "formula": "11_operating_profit Q",       "baseline": ">0 kinh doanh có lãi",                      "unit": _UNIT_KBS_MONEY},
    "is_eps"              : {"desc": "EPS kỳ báo cáo",       "formula": "19_earnings_per_share Q",     "baseline": "Cao = lãi trên cổ phiếu tốt",               "unit": _UNIT_VND_CP},
    "is_rev_growth"       : {"desc": "Tăng trưởng DT QoQ",  "formula": "(rev_q-rev_q1)/rev_q1",       "baseline": ">20% +5đ | >10% +3đ | >0% +1đ | <-10% -3đ", "unit": _UNIT_PCT_DEC},
    "is_profit_growth"    : {"desc": "Tăng trưởng LN QoQ",  "formula": "(np_q-np_q1)/np_q1",          "baseline": ">20% +5đ | >10% +3đ | >0% +1đ | <-10% -3đ", "unit": _UNIT_PCT_DEC},
    "is_rev_growth_yoy"   : {"desc": "Tăng trưởng DT YoY",  "formula": "(rev_q-rev_q4)/rev_q4",       "baseline": ">10% tốt >20% rất tốt",                     "unit": _UNIT_PCT_DEC},
    "is_profit_growth_yoy": {"desc": "Tăng trưởng LN YoY",  "formula": "(np_q-np_q4)/np_q4",          "baseline": ">10% tốt >20% rất tốt",                     "unit": _UNIT_PCT_DEC},

    # ── Fundamental — Balance Sheet (KBS, nghìn đồng → tỷ sau format) ──
    "bs_total_assets": {"desc": "Tổng tài sản",             "formula": "a_short + b_long assets Q",   "baseline": "Tăng ổn định tích cực",                     "unit": _UNIT_KBS_MONEY},
    "bs_equity"      : {"desc": "Vốn chủ sở hữu",          "formula": "owner_equity Q",              "baseline": "Tăng = tích lũy nội tại",                   "unit": _UNIT_KBS_MONEY},
    "bs_total_liab"  : {"desc": "Tổng nợ phải trả",        "formula": "total_liabilities Q",         "baseline": "Nợ/VCSH < 1 an toàn",                       "unit": _UNIT_KBS_MONEY},
    "bs_short_debt"  : {"desc": "Nợ vay ngắn hạn",         "formula": "short_term_borrowing Q",      "baseline": "Thấp = ít rủi ro thanh khoản",              "unit": _UNIT_KBS_MONEY},
    "bs_long_debt"   : {"desc": "Nợ vay dài hạn",          "formula": "long_term_borrowing Q",       "baseline": "Vừa phải tùy ngành",                        "unit": _UNIT_KBS_MONEY},

    # ── Cash Flow (KBS, nghìn đồng → tỷ sau format) ──
    "cf_operating"    : {"desc": "CF hoạt động KD",         "formula": "i_cash_flows_from_operating Q","baseline": ">0 +5đ | <0 -10đ",                         "unit": _UNIT_KBS_MONEY},
    "cf_investing"    : {"desc": "CF đầu tư",               "formula": "investing_cash_flow Q",       "baseline": "<0 đầu tư mở rộng bình thường",             "unit": _UNIT_KBS_MONEY},
    "cf_financing"    : {"desc": "CF tài chính",             "formula": "financing_cash_flow Q",       "baseline": "<0 trả nợ tốt | >0 vay thêm",               "unit": _UNIT_KBS_MONEY},
    "cf_free"         : {"desc": "Free Cash Flow",           "formula": "cf_operating + cf_investing", "baseline": ">0 tự chủ tài chính",                       "unit": _UNIT_KBS_MONEY},
    "cf_quality_ratio": {"desc": "Chất lượng lợi nhuận",    "formula": "cf_operating/is_net_profit",  "baseline": ">1 +5đ | <0.5 -5đ",                        "unit": _UNIT_RATIO},

    # ── Finance Score (precomputed từ finance/cache.json) ──
    "finance_score"       : {"desc": "Điểm tài chính tổng", "formula": "fund+cf+growth (precomputed)","baseline": "Max 38đ | từ finance/cache.json",            "unit": _UNIT_SCORE},
    "finance_score_fund"  : {"desc": "Điểm fundamental",    "formula": "PE+PB+ROE",                   "baseline": "Max ±18đ",                                   "unit": _UNIT_SCORE},
    "finance_score_cf"    : {"desc": "Điểm cash flow",      "formula": "CFO+CF quality",              "baseline": "Max ±10đ",                                   "unit": _UNIT_SCORE},
    "finance_score_growth": {"desc": "Điểm tăng trưởng",    "formula": "rev_growth+profit_growth",    "baseline": "Max ±10đ",                                   "unit": _UNIT_SCORE},

    # ── Market Cap ──
    "market_cap"      : {"desc": "Vốn hóa thị trường",     "formula": "price×outstanding_shares",    "baseline": ">10,000 Large | >1,000 Mid | <1,000 Small",  "unit": _UNIT_FF_MONEY},
    "market_cap_group": {"desc": "Phân loại quy mô",       "formula": "market_cap phân loại",        "baseline": "Large/Mid/Small cap",                        "unit": _UNIT_NONE},

    # ── Market Context ──
    "vnindex_pe"      : {"desc": "PE VNINDEX hiện tại",     "formula": "Analytics(VND).valuation(5Y)","baseline": "So với mean 5Y",                             "unit": _UNIT_RATIO},
    "pe_percentile_5y": {"desc": "PE percentile 5 năm",    "formula": "rank(PE_current, PE_5Y)",     "baseline": "<30% rẻ | >70% đắt",                         "unit": _UNIT_PCT_DEC},
    "pb_percentile_5y": {"desc": "PB percentile 5 năm",    "formula": "rank(PB_current, PB_5Y)",     "baseline": "<30% rẻ | >70% đắt",                         "unit": _UNIT_PCT_DEC},
    "market_valuation": {"desc": "Định giá thị trường",    "formula": "pe_percentile phân loại",     "baseline": "CHEAP +5đ | FAIR 0đ | EXPENSIVE -5đ",         "unit": _UNIT_NONE},

    # ── Scoring ──
    "trend_score"      : {"desc": "Điểm xu hướng",          "formula": "EMA cross+Price>EMA+ADX+Supertrend","baseline": "Max ±30đ | flat: EMA×0.5",              "unit": _UNIT_SCORE},
    "momentum_score"   : {"desc": "Điểm momentum",          "formula": "RSI+MACD hist+Stoch zone+cross",  "baseline": "Max ±23đ | flat: MACD×0.5",             "unit": _UNIT_SCORE},
    "volume_score"     : {"desc": "Điểm volume",            "formula": "CMF+MFI+OBV+BB position",     "baseline": "Max ±20đ",                                   "unit": _UNIT_SCORE},
    "ff_score"         : {"desc": "Điểm dòng tiền ngoại",   "formula": "FF net5d+net20d+trend+accel",  "baseline": "Max ±20đ",                                   "unit": _UNIT_SCORE},
    "fundamental_score": {"desc": "Điểm cơ bản",           "formula": "PE+PB+ROE",                   "baseline": "Max ±18đ",                                   "unit": _UNIT_SCORE},
    "cf_score"         : {"desc": "Điểm chất lượng CF",     "formula": "CFO+CF quality ratio",        "baseline": "Max ±10đ",                                   "unit": _UNIT_SCORE},
    "growth_score"     : {"desc": "Điểm tăng trưởng",       "formula": "rev_growth+profit_growth",    "baseline": "Max ±10đ",                                   "unit": _UNIT_SCORE},
    "context_score"    : {"desc": "Điểm context thị trường","formula": "market_valuation",            "baseline": "Max ±5đ",                                    "unit": _UNIT_SCORE},
    "news_score"       : {"desc": "Điểm tin tức tổng hợp",  "formula": "industry+mention+macro",      "baseline": "0–10đ | 5=neutral | ≥8 tích cực | ≤2 tiêu cực","unit": _UNIT_SCORE},
    "news_industry"    : {"desc": "Tin tức theo ngành",     "formula": "avg(weighted_sentiment) ngành ICB","baseline": "0–4đ | 2=neutral",                     "unit": _UNIT_SCORE},
    "news_mention"     : {"desc": "Tin đề cập trực tiếp",   "formula": "avg(weighted_sentiment×1.5) khi symbol in title","baseline": "0–4đ | 2=neutral | boost 1.5×","unit": _UNIT_SCORE},
    "news_macro"       : {"desc": "Tin vĩ mô thị trường",   "formula": "MACRO_KEYWORDS matched × bias","baseline": "0–2đ | 1=neutral | dùng chung toàn thị trường","unit": _UNIT_SCORE},
    "news_evidence"    : {"desc": "Dẫn chứng tin tức",      "formula": "top 3 articles by |contribution|","baseline": "[type] source: title (HH:MM) score",    "unit": _UNIT_NONE},
    "total_score"      : {"desc": "Tổng điểm",              "formula": "Σ trend+momentum+volume+ff+fund+cf+growth+ctx+news","baseline": "≥70 STRONG BUY | ≥50 BUY | ≥30 NEUTRAL | ≥10 SELL | <10 STRONG SELL","unit": _UNIT_SCORE},
    "decision"         : {"desc": "Quyết định",             "formula": "total_score phân loại",       "baseline": "STRONG BUY/BUY/NEUTRAL/SELL/STRONG SELL",    "unit": _UNIT_NONE},
    "signals"          : {"desc": "Chi tiết tín hiệu",      "formula": "list signals với điểm",       "baseline": "-",                                          "unit": _UNIT_NONE},
    "atr_pct"          : {"desc": "ATR% biến động tương đối","formula": "ATR(14)/price×100",          "baseline": "<0.5% flat(EMA/MACD×0.5) | >1.5% mạnh",     "unit": _UNIT_PCT_DEC},
}
