import unittest

import numpy as np
import pandas as pd

from scripts.vnstock6_v4_scoring import (
    PROFILES,
    classify_regime,
    factor_values,
    indicator_snapshot,
    score_profile,
    signal_values,
)


class Gen6V4ScoringTest(unittest.TestCase):
    def setUp(self):
        size = 260
        x = np.arange(size, dtype=float)
        self.frame = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=size).strftime("%Y-%m-%d"),
            "open": 100 + x * 0.1,
            "high": 102 + x * 0.1,
            "low": 98 + x * 0.1,
            "close": 100 + x * 0.1,
            "volume": 1_000_000 + x * 100,
        })
        self.quant = {
            "ema20": 124.0, "ema50": 122.0, "ema200": 115.0,
            "rsi14": 60.0, "atr14": 2.0, "obv": 1_000.0,
        }

    def test_indicator_snapshot_surfaces_computable_technical_fields(self):
        result = indicator_snapshot(self.frame, self.quant, 3.0)
        for key in (
            "atr_14", "atr_pct", "obv", "macd", "macd_signal",
            "macd_histogram", "willr_14", "stoch_k", "bb_mid",
            "bb_lower", "bb_upper", "bb_position", "cmf", "adtv_bil",
            "price_vs_ema200_pct", "relative_return_20d", "entry",
            "stop", "tp1", "tp2",
        ):
            self.assertIsNotNone(result[key], key)

    def test_regime_uses_only_rows_before_signal_date(self):
        rows = self.frame[["date", "open", "high", "low", "close", "volume"]].to_dict("records")
        signal_date = rows[-2]["date"]
        baseline = classify_regime(rows, signal_date)
        rows[-1]["close"] = 1.0
        self.assertEqual(classify_regime(rows, signal_date), baseline)
        self.assertLess(baseline["as_of"], signal_date)

    def test_unavailable_external_flow_is_explicitly_excluded(self):
        indicators = indicator_snapshot(self.frame, self.quant, 3.0)
        signals = signal_values(
            indicators,
            {"fundamental": 0.4, "growth": 0.2},
            "UPTREND",
        )
        factors = factor_values(signals)
        self.assertIsNone(factors["flow"])
        for version in PROFILES:
            result = score_profile(version, factors, "UPTREND")
            self.assertIn("flow", result["excluded_factors"])
            self.assertEqual(result["factor_status"]["flow"]["reason"], "source_unavailable")
            self.assertLess(result["available_weight"], 1.0)


if __name__ == "__main__":
    unittest.main()