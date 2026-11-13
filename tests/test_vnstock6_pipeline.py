import unittest
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vnstock6_native_pipeline as pipeline


class PipelineCadenceTest(unittest.TestCase):
    def test_intraday_bars_are_aggregated_into_current_daily_candle(self):
        frame = pd.DataFrame(
            {
                "time": ["2026-11-13 09:00:00", "2026-11-13 09:05:00"],
                "open": [100, 102],
                "high": [103, 106],
                "low": [99, 101],
                "close": [102, 105],
                "volume": [1000, 1500],
            }
        )
        rows = pipeline.normalize_ohlcv(frame, "FPT", "ssi")
        self.assertEqual(
            rows,
            [{
                "symbol": "FPT", "date": "2026-11-13", "market_source": "SSI",
                "pipeline_generation": 6, "open": 100.0, "high": 106.0,
                "low": 99.0, "close": 105.0, "volume": 2500.0,
            }],
        )
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

    def test_fundamental_ttl_matches_legacy_earnings_cadence(self):
        config = {
            "fundamental_refresh": {
                "max_age_days": 30,
                "earnings_max_age_days": 3,
                "earnings_months": [1, 2, 4],
            }
        }
        self.assertEqual(
            pipeline.fundamental_ttl_days(
                config, datetime(2026, 2, 10, tzinfo=timezone.utc)
            ),
            3,
        )
        self.assertEqual(
            pipeline.fundamental_ttl_days(
                config, datetime(2026, 3, 10, tzinfo=timezone.utc)
            ),
            30,
        )

    def test_stale_fundamentals_select_only_expired_symbols(self):
        config = {
            "universe": ["FPT", "SSI"],
            "fundamental_refresh": {
                "max_age_days": 30,
                "earnings_max_age_days": 3,
                "earnings_months": [11],
            },
        }
        cache = {
            "FPT": {"refreshed_at": datetime.now(timezone.utc).isoformat()},
            "SSI": {
                "refreshed_at": (
                    datetime.now(timezone.utc) - timedelta(days=4)
                ).isoformat()
            },
        }
        self.assertEqual(
            pipeline.stale_fundamental_symbols(
                config, cache, datetime(2026, 11, 13, tzinfo=timezone.utc)
            ),
            ["SSI"],
        )
    def test_stale_only_skips_source_calls_when_cache_is_fresh(self):
        config = {
            "sources": {"reference": "ssi", "fundamental": "fhsc"},
            "universe": ["FPT", "SSI"],
            "fundamental_refresh": {
                "max_age_days": 30,
                "earnings_max_age_days": 3,
                "earnings_months": [11],
            },
        }
        fresh = {
            symbol: {"refreshed_at": datetime.now(timezone.utc).isoformat()}
            for symbol in config["universe"]
        }
        with patch.object(
            pipeline, "load_fundamental_cache", return_value=fresh
        ), patch.object(
            pipeline, "fundamental_factors"
        ) as fetch, patch.object(
            Path, "mkdir"
        ), patch.object(
            Path, "write_text"
        ):
            status = pipeline.refresh_fundamental_cache(config, stale_only=True)
        fetch.assert_not_called()
        self.assertEqual(status["symbols_requested"], 0)
        self.assertEqual(status["counts"]["skipped_fresh"], 2)

if __name__ == "__main__":
    unittest.main()
