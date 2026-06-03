# ═════════════════════════════════════════════
    # MARKET CONTEXT (max ±5) — REGIME-AWARE (2026-06-03)
    # Kết hợp valuation (đắt/rẻ) + regime (xu hướng VNINDEX).
    # Lý do: "rẻ trong downtrend" = bẫy giá trị (bắt dao rơi) → KHÔNG thưởng.
    #        "giảm sâu" = rủi ro hệ thống → phạt điểm bất kể valuation.
    # Ma trận:
    #                 UPTREND  SIDEWAYS  DOWNTREND  DEEP_DOWN
    #   CHEAP           +5        +3         0          -2
    #   FAIR            +2         0        -2          -4
    #   EXPENSIVE       -2        -3        -4          -5
    # regime=UNKNOWN (API fail) → fallback valuation thuần (CHEAP+5/EXP-5).
    # ═════════════════════════════════════════════
    regime = context.get("market_regime", "UNKNOWN")

    CONTEXT_MATRIX = {
        "CHEAP":     {"UPTREND": 5, "SIDEWAYS": 3, "DOWNTREND":  0, "DEEP_DOWN": -2},
        "FAIR":      {"UPTREND": 2, "SIDEWAYS": 0, "DOWNTREND": -2, "DEEP_DOWN": -4},
        "EXPENSIVE": {"UPTREND": -2,"SIDEWAYS": -3,"DOWNTREND": -4, "DEEP_DOWN": -5},
    }

    if regime == "UNKNOWN":
        # Fallback: valuation thuần như logic cũ (không có data trend)
        if market == "CHEAP":       add("context",  5, "Market CHEAP")
        elif market == "EXPENSIVE": add("context", -5, "Market EXPENSIVE")
        else:                       add("context",  0, "Market FAIR")
    else:
        pts = CONTEXT_MATRIX.get(market, CONTEXT_MATRIX["FAIR"]).get(regime, 0)
        regime_vn = {
            "UPTREND": "uptrend", "SIDEWAYS": "sideways",
            "DOWNTREND": "downtrend", "DEEP_DOWN": "giam sau",
        }.get(regime, regime)
        add("context", pts, f"Market {market}+{regime_vn}")
