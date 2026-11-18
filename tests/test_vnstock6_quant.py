import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from scripts.vnstock6_quant import _growth, _is_financial_industry, _statement_signature, technical_indicators

class QuantIndicatorsTest(unittest.TestCase):
    def test_statement_signature_is_order_independent_and_value_sensitive(self):
        original=pd.DataFrame({"period":["2026Q1","2026Q2"],"id":["A","A"],"value":[1,2]})
        reordered=original.iloc[::-1].reset_index(drop=True)
        changed=original.copy(); changed.loc[1,"value"]=3
        blank=pd.DataFrame(columns=original.columns)
        self.assertEqual(
            _statement_signature([original,blank,blank]),
            _statement_signature([reordered,blank,blank]),
        )
        self.assertNotEqual(
            _statement_signature([original,blank,blank]),
            _statement_signature([changed,blank,blank]),
        )
    def test_growth_returns_actual_latest_quarter_yoy_rate(self):
        frame = pd.DataFrame({
            "period": ["2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1"],
            "id": ["IS_NET_REVENUE"] * 5,
            "value": [100, 110, 120, 130, 125],
        })
        self.assertAlmostEqual(_growth([frame], ("IS_NET_REVENUE",)), 0.25)

    def test_financial_industry_detection_handles_vietnamese_accents(self):
        self.assertTrue(_is_financial_industry("Ngân hàng"))
        self.assertTrue(_is_financial_industry("Chứng khoán"))
        self.assertTrue(_is_financial_industry("Dịch vụ tài chính"))
        self.assertTrue(_is_financial_industry("Insurance"))
        self.assertFalse(_is_financial_industry("Công nghệ"))

    def test_quant_adapter_maps_baseline_indicators_without_spending_live_quota(self):
        size=260
        frame=pd.DataFrame({
            "open":np.arange(size,dtype=float)+10,
            "high":np.arange(size,dtype=float)+11,
            "low":np.arange(size,dtype=float)+9,
            "close":np.arange(size,dtype=float)+10.5,
            "volume":np.arange(size,dtype=float)+1000,
        })

        def fake_compute(data, name, **params):
            self.assertEqual(len(data), size)
            return pd.Series(np.arange(size, dtype=float) + 1)

        with patch("scripts.vnstock6_quant.ta.compute", side_effect=fake_compute) as compute:
            result=technical_indicators(frame)

        self.assertEqual(compute.call_count,6)
        self.assertEqual(result["engine"],"vnstock_quant.ta")
        self.assertEqual(result["version"],"1.0.0")
        for key in ("ema20","ema50","ema200","rsi14","atr14","obv","adx14","supertrend"):
            self.assertIsNotNone(result[key],key)
        self.assertEqual(result["errors"],{})
if __name__ == "__main__":
    unittest.main()
