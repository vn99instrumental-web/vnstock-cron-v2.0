from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts import shared_raw_collector as collector
from scripts.vnstock6_quant import fundamental_factors_from_frames
from scripts.vnstock6_raw_adapter import RawRelease, fundamental_frames, market_factors_from_raw
from tests.test_shared_raw_collector import FakeTransport, config

ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / ".tmp" / "vnstock6-raw-adapter-tests"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)


class Gen6RawAdapterTests(unittest.TestCase):
    def test_exact_release_is_verified_and_market_factors_are_gen6_owned(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp)
            manifest = collector.collect_release(
                config(), FakeTransport(), root, cadence="weekly",
                signal_date=date(2026, 11, 25),
                created_at=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc),
            )
            raw = RawRelease.load(manifest["release_id"], root)
            self.assertEqual(raw.manifest["cadence"], "weekly")
            self.assertTrue(raw.rows("ohlcv", "FPT"))
            for frame in fundamental_frames(raw, "FPT"):
                self.assertTrue({"period", "id", "value"} <= set(frame.columns))
            factors = market_factors_from_raw(
                raw, ["FPT"], date(2026, 11, 25), refresh_slow=True, fetch_depth=True,
            )["FPT"]
            self.assertEqual(factors["raw_release_id"], manifest["release_id"])
            self.assertEqual(factors["endpoint_sources"]["foreign_flow"], "SSI")
            self.assertEqual(factors["endpoint_sources"]["order_book"], "FHSC")
            self.assertIsNotNone(factors["s_ff_net"])

    def test_fundamental_frames_use_vnstock_quant_not_ssi_formulas(self):
        balance = pd.DataFrame({"period": ["2026Q3"], "id": ["BS_TOTAL_ASSETS"], "value": [100]})
        income = pd.DataFrame({
            "period": ["2025Q3", "2025Q4", "2026Q1", "2026Q2", "2026Q3"],
            "id": ["IS_NET_PROFIT_AFTER_TAX"] * 5, "value": [10, 11, 12, 13, 15],
        })
        cash = pd.DataFrame({"period": ["2026Q3"], "id": ["CF_OPERATING"], "value": [18]})
        ratios = pd.DataFrame({
            "period": ["2026Q3"], "id": ["RT_PRT_ROE"], "value": [0.15],
        })
        with patch("scripts.vnstock6_quant.fa.Dataset.from_frames", return_value=object()) as dataset, patch(
            "scripts.vnstock6_quant.fa.ratios", return_value=ratios,
        ) as ratio_engine:
            result = fundamental_factors_from_frames("FPT", [balance, income, cash], "Technology")
        dataset.assert_called_once()
        ratio_engine.assert_called_once()
        self.assertEqual(result["engine"], "vnstock_quant.fa")
        self.assertEqual(result["ratios"]["RT_PRT_ROE"], 0.15)
        self.assertNotIn("error", result)


if __name__ == "__main__":
    unittest.main()