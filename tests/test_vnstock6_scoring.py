import unittest
from scripts.vnstock6_scoring import availability_score

WEIGHTS = {"trend": .25, "momentum": .25, "breakout": .05, "liquidity": .15, "fundamental": .20, "growth": .10}

class AvailabilityScoreTest(unittest.TestCase):
    def test_missing_factors_are_excluded_and_weight_is_renormalized(self):
        result = availability_score({"price": 110, "ema20": 100, "ema50": 90, "rsi14": 55, "return20": 8, "volume_ratio": None, "fundamental": None, "growth": None}, WEIGHTS)
        self.assertEqual(result["excluded_factors"], ["liquidity", "fundamental", "growth"])
        self.assertAlmostEqual(result["available_weight"], .55)
        self.assertEqual(result["score"], 100.0)

    def test_no_available_factor_fails_closed(self):
        with self.assertRaises(ValueError):
            availability_score({}, WEIGHTS)

if __name__ == "__main__":
    unittest.main()