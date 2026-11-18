import unittest
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vnstock6_native_pipeline as pipeline


class PipelineCadenceTest(unittest.TestCase):
    def test_market_cache_writer_normalizes_nested_order_book(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as folder:
            cache_path = Path(folder) / "market-factors.json"
            with patch.object(pipeline, "MARKET_FACTOR_CACHE", cache_path):
                pipeline.save_market_factor_cache({
                    "FPT": {"raw": {"order_book": [{
                        "time": pd.Timestamp("2026-11-17 09:30:00"),
                        "bid_volume_1": 1200,
                        "ask_volume_1": float("nan"),
                    }]}}
                })
            saved = json.loads(cache_path.read_text(encoding="utf-8"))
        record = saved["symbols"]["FPT"]["raw"]["order_book"][0]
        self.assertEqual(record["time"], "2026-11-17T09:30:00")
        self.assertEqual(record["bid_volume_1"], 1200)
        self.assertIsNone(record["ask_volume_1"])

    def test_daily_close_uses_actual_execution_time(self):
        now = datetime(2026, 11, 17, 8, 20, tzinfo=timezone.utc)
        self.assertEqual(pipeline.scoring_snap_time(now, False), "08:20")
        self.assertEqual(pipeline.scoring_snap_time(now, True), "08:20")

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
        fresh = {"version": "1.1.0", "refreshed_at": datetime.now(timezone.utc).isoformat()}
        stale = {"version": "1.1.0", "refreshed_at": (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()}
        self.assertTrue(pipeline.cache_entry_is_fresh(fresh, 14))
        self.assertFalse(pipeline.cache_entry_is_fresh(stale, 14))
        self.assertFalse(pipeline.cache_entry_is_fresh({}, 14))
        self.assertTrue(pipeline.cache_entry_is_fresh({"version": "1.0.0", "refreshed_at": fresh["refreshed_at"]}, 14))

    def test_fundamental_material_compare_ignores_refresh_metadata(self):
        before = {
            "fundamental": 0.4, "statement_signature": "same",
            "checked_at": "2026-11-16T01:00:00Z",
            "latest_income_signature": "probe-only",
            "latest_statement_signature": "composite-probe-only",
            "latest_statement_signatures": {"income-statement": "probe-only"},
            "statements": {"income": {"rows": 4, "fetched_at": "old"}},
        }
        after = {
            "fundamental": 0.4, "statement_signature": "same",
            "checked_at": "2026-11-17T01:00:00Z",
            "statements": {"income": {"rows": 4, "fetched_at": "new"}},
        }
        self.assertEqual(
            pipeline.fundamental_material_value(before), pipeline.fundamental_material_value(after)
        )

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
            "FPT": {"version": "1.1.0", "refreshed_at": datetime.now(timezone.utc).isoformat()},
            "SSI": {
                "version": "1.1.0",
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
    def test_daily_check_preserves_unchanged_factors(self):
        config = {
            "sources": {"reference": "ssi", "fundamental": "fhsc"},
            "universe": ["FPT"],
            "fundamental_refresh": {
                "max_age_days": 30,
                "earnings_max_age_days": 3,
                "earnings_months": [11],
            },
        }
        previous = {
            "version": "1.1.0", "statement_signature": "same",
            "latest_statement_signature": "latest-same",
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "fundamental": 0.4, "growth": 0.2,
            "growth_revenue_yoy": 0.1, "growth_profit_yoy": 0.2,
        }
        reference = pd.DataFrame({"symbol": ["FPT"], "industry": ["Technology"]})
        unchanged = {
            "unchanged": True, "statement_signature": "same",
            "statements": {"balance_sheet": {"status": "success"}},
        }
        with patch.object(pipeline, "load_fundamental_cache", return_value={"FPT": previous}), patch.object(
            pipeline, "Reference"
        ) as reference_factory, patch.object(
            pipeline, "latest_statement_probe",
            return_value={
                "signature": "latest-same", "period": "2026-Q3", "rows": 3,
                "request_count": 3,
                "periods": {
                    "income-statement": "2026-Q3", "balance-sheet": "2026-Q3",
                    "cash-flow": "2026-Q3",
                },
                "statement_signatures": {
                    "income-statement": "income-same", "balance-sheet": "balance-same",
                    "cash-flow": "cash-same",
                },
            },
        ), patch.object(
            pipeline, "fundamental_factors", return_value=unchanged
        ) as fetch, patch.object(
            pipeline, "save_fundamental_cache"
        ) as save, patch.object(Path, "mkdir"), patch.object(Path, "write_text"):
            reference_factory.return_value.equity.list.return_value = reference
            status = pipeline.refresh_fundamental_cache(config, check_updates=True)
        self.assertEqual(status["counts"]["unchanged"], 1)
        self.assertEqual(status["counts"]["updated"], 0)
        fetch.assert_not_called()
        saved = save.call_args.args[1]["FPT"]
        self.assertEqual(saved["fundamental"], 0.4)
        self.assertEqual(saved["growth"], 0.2)
        self.assertIn("checked_at", saved)

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
            symbol: {"version": "1.1.0", "refreshed_at": datetime.now(timezone.utc).isoformat()}
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

    def test_legacy_cash_flow_overlay_fills_only_missing_values(self):
        payload = {
            "generated_at": "2026-11-09T01:00:00+00:00",
            "symbols": {
                "FPT": {
                    "fetched_at": "2026-11-09T01:00:00+00:00",
                    "period": "2026-Q3",
                    "finance_score": {"cashflow": 5},
                    "cashflow": {"cf_operating": 120, "cf_quality": 1.2},
                }
            },
        }
        with patch.object(pipeline, "LEGACY_FINANCE_CACHE") as cache_path:
            cache_path.exists.return_value = True
            cache_path.read_text.return_value = json.dumps(payload)
            factors, restored = pipeline.overlay_legacy_cash_flow({"FPT": {"fundamental": .4}}, ["FPT"])
        self.assertEqual(restored, 1)
        self.assertEqual(factors["FPT"]["cash_flow_score"], 5)
        self.assertEqual(factors["FPT"]["cash_flow"], .5)
        self.assertEqual(factors["FPT"]["cash_flow_source"], "legacy_finance_cache")

    def test_depth_cache_prefers_complete_in_session_snapshot(self):
        rows = [
            {"symbol": "FPT", "signal_date": "2026-11-16", "snap_time": "14:19", "scoring_version": "v6.4.18", "s_depth_wall": 2},
            {"symbol": "SSI", "signal_date": "2026-11-16", "snap_time": "14:19", "scoring_version": "v6.4.18", "s_depth_wall": 1},
            {"symbol": "FPT", "signal_date": "2026-11-16", "snap_time": "17:14", "scoring_version": "v6.4.18", "s_depth_wall": 3},
        ]
        payload = "".join(json.dumps(row) + "\n" for row in rows)
        with patch.object(Path, "glob", return_value=[Path("2026-11-16.jsonl")]), patch.object(
            Path, "read_text", return_value=payload
        ):
            cached = pipeline.load_best_depth_snapshot("v6.4.18")
        self.assertEqual(set(cached), {"FPT", "SSI"})
        self.assertEqual(cached["FPT"]["depth_snap_time"], "14:19")


if __name__ == "__main__":
    unittest.main()
