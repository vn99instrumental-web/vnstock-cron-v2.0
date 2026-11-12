import unittest
import numpy as np
import pandas as pd
from scripts.vnstock6_quant import technical_indicators

class QuantIndicatorsTest(unittest.TestCase):
    def test_pinned_quant_engine_calculates_baseline_indicators(self):
        size=260
        frame=pd.DataFrame({
            "open":np.arange(size,dtype=float)+10,
            "high":np.arange(size,dtype=float)+11,
            "low":np.arange(size,dtype=float)+9,
            "close":np.arange(size,dtype=float)+10.5,
            "volume":np.arange(size,dtype=float)+1000,
        })
        result=technical_indicators(frame)
        self.assertEqual(result["engine"],"vnstock_quant.ta")
        self.assertEqual(result["version"],"1.0.0")
        for key in ("ema20","ema50","ema200","rsi14","atr14","obv"):
            self.assertIsNotNone(result[key],key)
        self.assertEqual(result["errors"],{})

if __name__ == "__main__":
    unittest.main()
