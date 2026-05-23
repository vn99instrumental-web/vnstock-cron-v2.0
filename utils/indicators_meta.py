"""
Metadata cho tất cả indicators:
  desc     : mô tả ngắn gọn
  formula  : công thức tính
  baseline : ngưỡng tham chiếu + điểm
"""

INDICATORS_META = {
    # ── Primary keys ──
    "symbol"         : {"desc": "Mã cổ phiếu",          "formula": "-",                          "baseline": "-"},
    "group"          : {"desc": "Nhóm tăng/giảm",        "formula": "-",                          "baseline": "GAINER/LOSER"},
    "industry"       : {"desc": "Ngành",                  "formula": "-",                          "baseline": "-"},
    "time"           : {"desc": "Thời gian cập nhật",     "formula": "-",                          "baseline": "-"},
    "date"           : {"desc": "Ngày giao dịch",         "formula": "-",                          "baseline": "-"},

    # ── Snapshot ──
    "price"          : {"desc": "Giá hiện tại",           "formula": "last_price",                 "baseline": "-"},
    "price_type"     : {"desc": "Loại giá",               "formula": "-",                          "baseline": "realtime/last_close"},
    "intra_buy_vol"  : {"desc": "KL mua chủ động",        "formula": "Σ vol match_type=Buy",       "baseline": "Cao = áp lực mua"},
    "intra_sell_vol" : {"desc": "KL bán chủ động",        "formula": "Σ vol match_type=Sell",      "baseline": "Cao = áp lực bán"},
    "intra_delta"    : {"desc": "Chênh lệch mua-bán",     "formula": "buy_vol - sell_vol",         "baseline": ">0 mua nhiều hơn"},
    "intra_buy_ratio": {"desc": "Tỷ lệ mua chủ động",    "formula": "buy_vol/(buy+sell)",         "baseline": ">0.6 mua mạnh"},
    "depth_buy"      : {"desc": "KL chờ mua (depth)",     "formula": "Σ buy_volume depth",         "baseline": "Cao = nhu cầu mua"},
    "depth_sell"     : {"desc": "KL chờ bán (depth)",     "formula": "Σ sell_volume depth",        "baseline": "Cao = áp lực bán"},
    "depth_buy_ratio": {"desc": "Tỷ lệ mua/tổng depth",  "formula": "depth_buy/(buy+sell)",       "baseline": ">0.6 thiên mua"},

    # ── Ranking ──
    "last_price"             : {"desc": "Giá đóng cửa",          "formula": "-",                          "baseline": "-"},
    "price_change_1d"        : {"desc": "Thay đổi giá tuyệt đối","formula": "price - prev_close",         "baseline": "-"},
    "price_change_pct_1d"    : {"desc": "% thay đổi giá",        "formula": "(price-prev)/prev×100",      "baseline": ">0 tăng <0 giảm"},
    "accumulated_value"      : {"desc": "Giá trị GD tích lũy",   "formula": "Σ(price×vol) tỷ đồng",      "baseline": ">5 tỷ thanh khoản tốt"},
    "volume_spike_20d_pct"   : {"desc": "Volume đột biến vs 20D","formula": "vol/avg_vol_20d×100",        "baseline": ">200% đột biến mạnh"},
    "deal_volume_spike_20d_pct":{"desc":"Đột biến thỏa thuận",   "formula": "deal_vol/avg×100",           "baseline": ">100% có tổ chức vào"},

    # ── TA — Trend ──
    "ema20"          : {"desc": "EMA 20 ngày",            "formula": "EMA(close,20)",              "baseline": "Giá>EMA20 = uptrend"},
    "ema50"          : {"desc": "EMA 50 ngày",            "formula": "EMA(close,50)",              "baseline": "EMA20>EMA50 = bullish"},
    "ema_cross_pct"  : {"desc": "% EMA20 vs EMA50",       "formula": "(EMA20-EMA50)/EMA50×100",    "baseline": ">0 bullish <0 bearish"},
    "price_vs_ema20_pct":{"desc":"% giá vs EMA20",        "formula": "(price-EMA20)/EMA20×100",    "baseline": ">0 trên EMA20"},
    "adx"            : {"desc": "Sức mạnh xu hướng",      "formula": "ADX(14)",                    "baseline": ">25 mạnh <20 sideways"},
    "supertrend"     : {"desc": "Supertrend level",       "formula": "ST(10,3)",                   "baseline": "Giá>ST = uptrend"},

    # ── TA — Momentum ──
    "rsi"            : {"desc": "Relative Strength Index","formula": "RSI(14)",                    "baseline": "<30 oversold >70 overbought"},
    "macd"           : {"desc": "MACD line",              "formula": "EMA12-EMA26",                "baseline": ">0 bullish"},
    "macd_sig"       : {"desc": "MACD signal line",       "formula": "EMA9(MACD)",                 "baseline": "MACD cross up = buy"},
    "macd_hist"      : {"desc": "MACD histogram",         "formula": "MACD-signal",                "baseline": ">0 tăng <0 giảm"},
    "stoch_k"        : {"desc": "Stochastic %K",          "formula": "Stoch(14,3,3).K",            "baseline": "<20 oversold >80 overbought"},
    "stoch_d"        : {"desc": "Stochastic %D",          "formula": "Stoch(14,3,3).D",            "baseline": "K cross D up = buy"},

    # ── TA — Volatility ──
    "bb_upper"       : {"desc": "Bollinger Band trên",    "formula": "BB(20,2).upper",             "baseline": "Giá chạm = quá mua"},
    "bb_mid"         : {"desc": "Bollinger Band giữa",    "formula": "BB(20,2).mid=SMA20",         "baseline": "Hỗ trợ/kháng cự"},
    "bb_lower"       : {"desc": "Bollinger Band dưới",    "formula": "BB(20,2).lower",             "baseline": "Giá chạm = quá bán"},
    "bb_position"    : {"desc": "Vị trí giá trong BB",   "formula": "(price-lower)/(upper-lower)","baseline": "<0.2 đáy >0.8 đỉnh >1 breakout"},
    "atr"            : {"desc": "Average True Range",     "formula": "ATR(14)",                    "baseline": "Cao = biến động lớn"},

    # ── TA — Volume ──
    "obv"            : {"desc": "On Balance Volume",      "formula": "Σ±volume theo giá",          "baseline": "Tăng cùng giá = xác nhận"},
    "cmf"            : {"desc": "Chaikin Money Flow",     "formula": "CMF(20)",                    "baseline": ">0.1 inflow <-0.1 outflow"},
    "mfi"            : {"desc": "Money Flow Index",       "formula": "MFI(14)",                    "baseline": "<20 oversold >80 overbought"},

    # ── Foreign Flow ──
    "ff_buy_val_5d"  : {"desc": "FF mua 5 ngày (tỷ)",    "formula": "Σ fr_buy_val_matched 5d",    "baseline": "Cao = ngoại mua mạnh"},
    "ff_sell_val_5d" : {"desc": "FF bán 5 ngày (tỷ)",    "formula": "Σ fr_sell_val_matched 5d",   "baseline": "Cao = ngoại bán mạnh"},
    "ff_net_val_5d"  : {"desc": "FF ròng 5 ngày (tỷ)",   "formula": "buy-sell 5d",                "baseline": ">0 mua ròng <0 bán ròng"},
    "ff_net_val_20d" : {"desc": "FF ròng 20 ngày (tỷ)",  "formula": "buy-sell 20d",               "baseline": ">0 tích lũy <0 phân phối"},
    "ff_room"        : {"desc": "Room ngoại còn lại",     "formula": "fr_current_room",            "baseline": ">0 còn room mua"},
    "ff_trend"       : {"desc": "Xu hướng FF 20 ngày",   "formula": "slope(ff_net_20d)",          "baseline": ">0 tích lũy dần <0 phân phối"},
    "ff_consistency" : {"desc": "Tỷ lệ ngày FF dương",   "formula": "count(ff>0)/20",             "baseline": ">0.6 ngoại mua liên tục"},
    "ff_acceleration": {"desc": "FF tăng tốc",           "formula": "ff_net_5d vs ff_net_20d/4",  "baseline": ">0 đang tăng tốc mua"},

    # ── Insider ──
    "insider_count"  : {"desc": "Số GD nội bộ gần đây",  "formula": "count insider_deal(5)",      "baseline": "Mua = tin tưởng nội bộ"},
    "insider_latest" : {"desc": "GD nội bộ gần nhất",    "formula": "action_type.last",           "baseline": "Mua tích cực Bán tiêu cực"},
    "insider_name"   : {"desc": "Người GD nội bộ",       "formula": "trader_name.last",           "baseline": "-"},

    # ── Fundamental — Ratio ──
    "r_pe"           : {"desc": "P/E ratio",              "formula": "price/EPS",                  "baseline": "<15 rẻ 15-25 hợp lý >25 đắt"},
    "r_pb"           : {"desc": "P/B ratio",              "formula": "price/BVPS",                 "baseline": "<1 dưới sổ sách 1-3 hợp lý"},
    "r_eps"          : {"desc": "Earnings Per Share",     "formula": "net_profit/shares",          "baseline": "Càng cao càng tốt"},
    "r_bvps"         : {"desc": "Book Value Per Share",   "formula": "equity/shares",              "baseline": "Cao = tài sản thực nhiều"},
    "r_roe"          : {"desc": "Return on Equity %",     "formula": "net_profit/equity×100",      "baseline": ">15% tốt >20% rất tốt"},
    "r_roa"          : {"desc": "Return on Assets %",     "formula": "net_profit/assets×100",      "baseline": ">5% tốt >10% rất tốt"},
    "r_beta"         : {"desc": "Beta - độ biến động",   "formula": "cov(stock,market)/var(market)","baseline": "<1 ít biến động >1 biến động nhiều"},
    "r_div_yield"    : {"desc": "Tỷ suất cổ tức %",      "formula": "dividend/price×100",         "baseline": ">3% hấp dẫn"},
    "r_gross_margin" : {"desc": "Biên lợi nhuận gộp %",  "formula": "gross_profit/revenue×100",   "baseline": ">30% tốt tùy ngành"},
    "r_net_margin"   : {"desc": "Biên lợi nhuận ròng %", "formula": "net_profit/revenue×100",     "baseline": ">10% tốt tùy ngành"},
    "r_quick_ratio"  : {"desc": "Tỷ số thanh khoản",     "formula": "(current-inventory)/current_liab","baseline": ">1 đủ thanh khoản"},
    "r_interest_cov" : {"desc": "Khả năng trả lãi vay",  "formula": "EBIT/interest_expense",      "baseline": ">3 an toàn >5 rất tốt"},
    "r_ev_ebitda"    : {"desc": "EV/EBITDA định giá",    "formula": "EV/EBITDA",                  "baseline": "<10 rẻ 10-15 hợp lý >20 đắt"},

    # ── Fundamental — Income ──
    "is_revenue"     : {"desc": "Doanh thu thuần (tỷ)",  "formula": "net_revenue Q",              "baseline": "Tăng YoY tích cực"},
    "is_gross_profit": {"desc": "Lợi nhuận gộp (tỷ)",   "formula": "revenue-COGS",               "baseline": "Tăng = biên gộp tốt"},
    "is_net_profit"  : {"desc": "LNST (tỷ)",             "formula": "profit_after_tax Q",         "baseline": "Tăng YoY tích cực"},
    "is_operating_profit":{"desc":"Lợi nhuận HĐ (tỷ)",  "formula": "operating_profit Q",         "baseline": ">0 kinh doanh có lãi"},
    "is_eps"         : {"desc": "EPS kỳ (VND)",          "formula": "earnings_per_share Q",       "baseline": "Cao = lãi trên cổ phiếu tốt"},
    "is_rev_growth"  : {"desc": "Tăng trưởng DT % YoY", "formula": "(rev-rev_prev)/rev_prev×100","baseline": ">10% tốt >20% rất tốt"},
    "is_profit_growth":{"desc": "Tăng trưởng LN % YoY", "formula": "(np-np_prev)/np_prev×100",   "baseline": ">10% tốt >20% rất tốt"},

    # ── Fundamental — Balance Sheet ──
    "bs_total_assets": {"desc": "Tổng tài sản (tỷ)",    "formula": "total_assets Q",             "baseline": "Tăng ổn định tích cực"},
    "bs_equity"      : {"desc": "Vốn chủ sở hữu (tỷ)", "formula": "owner_equity Q",             "baseline": "Tăng = tích lũy nội tại"},
    "bs_total_liab"  : {"desc": "Tổng nợ (tỷ)",         "formula": "total_liabilities Q",        "baseline": "Nợ/VCS < 1 an toàn"},
    "bs_short_debt"  : {"desc": "Nợ vay ngắn hạn (tỷ)","formula": "short_term_borrowing Q",     "baseline": "Thấp = ít rủi ro thanh khoản"},
    "bs_long_debt"   : {"desc": "Nợ vay dài hạn (tỷ)", "formula": "long_term_borrowing Q",      "baseline": "Vừa phải tùy ngành"},

    # ── Cash Flow ──
    "cf_operating"   : {"desc": "CF hoạt động KD (tỷ)", "formula": "operating_cash_flow Q",      "baseline": ">0 tạo tiền thật"},
    "cf_investing"   : {"desc": "CF đầu tư (tỷ)",       "formula": "investing_cash_flow Q",      "baseline": "<0 đầu tư mở rộng bình thường"},
    "cf_financing"   : {"desc": "CF tài chính (tỷ)",    "formula": "financing_cash_flow Q",      "baseline": "<0 trả nợ tốt >0 vay thêm"},
    "cf_free"        : {"desc": "Free Cash Flow (tỷ)",  "formula": "CFO - CapEx",                "baseline": ">0 tự chủ tài chính"},
    "cf_quality_ratio":{"desc": "Chất lượng LN",        "formula": "cf_operating/net_profit",    "baseline": ">1 LN chất lượng cao <0.5 cảnh báo"},

    # ── Fundamental vs Industry ──
    "market_cap"     : {"desc": "Vốn hóa (tỷ)",         "formula": "price×shares",               "baseline": ">10000 large <1000 small"},
    "market_cap_group":{"desc":"Phân loại quy mô",       "formula": "market_cap phân loại",       "baseline": "Large/Mid/Small cap"},

    # ── Market Context ──
    "vnindex_pe"     : {"desc": "PE VNINDEX hiện tại",   "formula": "Analytics VND",              "baseline": "So với mean 5Y"},
    "pe_percentile_5y":{"desc": "PE percentile 5 năm",  "formula": "rank PE trong 5Y",           "baseline": "<30% rẻ >70% đắt"},
    "market_valuation":{"desc": "Định giá thị trường",  "formula": "pe_percentile phân loại",    "baseline": "CHEAP/FAIR/EXPENSIVE"},

    # ── Scoring ──
    "trend_score"    : {"desc": "Điểm xu hướng",         "formula": "EMA+ADX+ST+price_ema",      "baseline": "Max 25đ"},
    "momentum_score" : {"desc": "Điểm momentum",         "formula": "RSI+MACD+Stoch",             "baseline": "Max 20đ"},
    "volume_score"   : {"desc": "Điểm volume",           "formula": "CMF+MFI+OBV",               "baseline": "Max 15đ"},
    "ff_score"       : {"desc": "Điểm dòng tiền ngoại",  "formula": "FF net+trend+accel",         "baseline": "Max 20đ"},
    "fundamental_score":{"desc":"Điểm cơ bản",           "formula": "PE+PB+ROE",                  "baseline": "Max 15đ"},
    "cf_score"       : {"desc": "Điểm chất lượng CF",    "formula": "CFO+CF quality",             "baseline": "Max 10đ"},
    "context_score"  : {"desc": "Điểm context thị trường","formula":"market_valuation",           "baseline": "Max 5đ"},

    # ── News Sentiment ──
    "news_score"     : {"desc": "Điểm tin tức tổng hợp", "formula": "industry+mention+macro",     "baseline": "0-10đ | 5=neutral 8+=tích cực 2-=tiêu cực"},
    "news_industry"  : {"desc": "Tin tức theo ngành",    "formula": "avg(weighted_sentiment) ngành ICB của symbol", "baseline": "0-4đ | 2=neutral"},
    "news_mention"   : {"desc": "Tin đề cập trực tiếp",  "formula": "avg(weighted_sentiment×1.5) khi symbol trong title/tags", "baseline": "0-4đ | 2=neutral boost 1.5×"},
    "news_macro"     : {"desc": "Tin vĩ mô thị trường",  "formula": "MACRO_KEYWORDS matched × bias / total_articles", "baseline": "0-2đ | 1=neutral | dùng chung toàn thị trường"},
    "news_evidence"  : {"desc": "Dẫn chứng tin tức",     "formula": "top 3 articles by |contribution| per symbol", "baseline": "format: [type] source: title (HH:MM) score | type=mention/industry/macro"},
    "total_score"    : {"desc": "Tổng điểm",             "formula": "Σ all scores",               "baseline": ">=50 BUY >=70 STRONG BUY | Max 120đ"},
    "decision"       : {"desc": "Quyết định",            "formula": "total_score phân loại",      "baseline": "STRONG BUY/BUY/NEUTRAL/SELL/STRONG SELL"},
    "signals"        : {"desc": "Chi tiết tín hiệu",     "formula": "list signals",               "baseline": "-"},
}
