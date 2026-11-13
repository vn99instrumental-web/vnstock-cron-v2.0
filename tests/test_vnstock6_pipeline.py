import unittest
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vnstock6_native_pipeline as pipeline


class PipelineCadenceTest(unittest.TestCase):
    def test_market_fetch_start_uses_recent_correction_window(self):
        with patch.object(Path, "exists", return_value=True), patch.object(
            Path, "read_text", return_value='[{"date":"2026-11-10"}]'
        ):
            self.assertEqual(
                pipeline.market_fetch_start("FPT", date(2026, 11, 13), 500),
                "2026-10-27",
            )

    def test_market_fetch_start_bootstraps_when_cache_is_missing(self):
        with patch.object(Path, "exists", return_value=False):
            self.assertEqual(
                pipeline.market_fetch_start("FPT", date(2026, 11, 13), 500),
                "2025-07-01",
            )

    def test_cache_freshness_requires_timestamp_within_limit(self):
        fresh = {"refreshed_at": datetime.now(timezone.utc).isoformat()}
        stale = {"refreshed_at": (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()}
        self.assertTrue(pipeline.cache_entry_is_fresh(fresh, 14))
        self.assertFalse(pipeline.cache_entry_is_fresh(stale, 14))
        self.assertFalse(pipeline.cache_entry_is_fresh({}, 14))


if __name__ == "__main__":
    unittest.main()
