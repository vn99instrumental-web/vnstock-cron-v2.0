from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ssi_independent_pipeline", ROOT / "scripts" / "ssi_independent_pipeline.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SsiIndependentPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "config" / "ssi_independent.json").read_text(encoding="utf-8"))

    def sample(self):
        return {
            "symbol": "FPT", "signal_date": "2026-11-23", "snap_time": "15:30",
            "snapshot_at": "2026-11-23T15:30:00+07:00", "market_source": "SSI", "fundamental_source": "FHSC",
            "price": 100, "willr_14": -85, "bb_position": .1, "price_vs_ema200_pct": -5,
            "relative_return_20d": -3, "position_52w": .1, "adx": 27, "supertrend": 95,
            "vol_ma_ratio": 1.8, "of_vol_spike_pct": 30, "adtv_20d_bil": 100,
            "foreign_net_5d": 60_000_000_000, "foreign_net_20d": 100_000_000_000,
            "proprietary_net_5d": 6_000_000_000, "proprietary_net_20d": 10_000_000_000,
            "insider_buy_count": 4, "insider_sell_count": 1, "insider_unclassified_count": 0,
            "depth_bid_multiple": 120, "depth_ask_multiple": 20,
            "ratio_roe": .25, "ratio_roa": .12, "ratio_gross_margin": .4,
            "ratio_net_margin": .2, "ratio_current": 2, "ratio_debt_equity": .5,
            "growth_revenue_yoy": .2, "growth_profit_yoy": .3,
            "cash_flow_operating": 10, "cash_flow_quality": 1.2,
            "vnindex_close": 1200, "vnindex_ema20": 1150, "vnindex_ema50": 1100,
            "vnindex_ema200": 1000, "vnindex_return_20d": 5,
            "fundamental_metrics": {"industry": "Technology"},
        }

    def test_does_not_consume_gen6_scores_or_signals(self):
        first = self.sample()
        second = copy.deepcopy(first)
        for key in module.SIGNAL_SPANS:
            second[f"s_{key}"] = -999
        second.update({"score_trade": -999, "score_hold": -999, "decision": "STRONG SELL"})
        self.assertEqual(module.score_row(first, self.config), module.score_row(second, self.config))

    def test_missing_optional_flow_is_excluded_not_zero_filled(self):
        row = self.sample()
        for key in ("insider_buy_count", "insider_sell_count", "depth_bid_multiple", "depth_ask_multiple"):
            row[key] = None
        scored = module.score_row(row, self.config)
        self.assertEqual(scored["signal_coverage"], 15)
        self.assertEqual(set(scored["missing_signals"]), {"insider", "depth_wall"})
        self.assertIsInstance(scored["score_trade"], float)
        self.assertNotEqual(scored["decision"], "NOT_FOR_TRADING")

    def test_missing_phase_input_is_excluded_not_zero_filled(self):
        row = self.sample()
        row["of_vol_spike_pct"] = None
        scored = module.score_row(row, self.config)
        self.assertIsNone(scored["signals"]["of_phasefix"])
        self.assertIn("of_phasefix", scored["missing_signals"])

    def test_wrong_source_is_rejected(self):
        row = self.sample()
        row["market_source"] = "VCI"
        with self.assertRaisesRegex(ValueError, "MARKET_SOURCE"):
            module.score_row(row, self.config)

    def test_repository_build_has_full_latest_universe(self):
        dashboard = module.build()
        self.assertGreaterEqual(dashboard["summary"]["symbols"], 80)
        self.assertEqual(dashboard["summary"]["symbols"], dashboard["summary"]["scored_symbols"])
        self.assertTrue(all(row["source_provenance"]["gen6_scores_consumed"] is False for row in dashboard["latest"]))
        self.assertTrue(all(row["market_source"] == "SSI" and row["fundamental_source"] == "FHSC" for row in dashboard["latest"]))


if __name__ == "__main__":
    unittest.main()
