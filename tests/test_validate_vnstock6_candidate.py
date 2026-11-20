import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_vnstock6_candidate import (
    OPTIONAL_SOURCE_COVERAGE,
    REQUIRED_QUALITY_COVERAGE,
    fundamental_refresh_summary,
    github_command_escape,
    source_lag_days,
)


class FundamentalRefreshSummaryTest(unittest.TestCase):
    def test_same_session_source_fields_are_reported_but_not_release_blocking(self):
        self.assertIn("ff_intra_net", OPTIONAL_SOURCE_COVERAGE)
        self.assertIn("ff_intra_ratio", OPTIONAL_SOURCE_COVERAGE)
        self.assertNotIn("ff_intra_net", REQUIRED_QUALITY_COVERAGE)
        self.assertNotIn("ff_intra_ratio", REQUIRED_QUALITY_COVERAGE)

    def test_depth_quality_requires_atomic_raw_inputs(self):
        self.assertIn("s_depth_wall", REQUIRED_QUALITY_COVERAGE)
        self.assertIn("depth_average_trade_size", REQUIRED_QUALITY_COVERAGE)
        self.assertIn("order_book_bid_price", REQUIRED_QUALITY_COVERAGE)
        self.assertIn("order_book_ask_price", REQUIRED_QUALITY_COVERAGE)

    def test_github_command_escape_keeps_annotation_on_one_line(self):
        self.assertEqual(github_command_escape("bad%\nvalue\r"), "bad%25%0Avalue%0D")

    def test_source_lag_uses_signal_and_source_dates(self):
        self.assertEqual(source_lag_days("2026-11-17", "2026-11-20"), 3)
        self.assertIsNone(source_lag_days(None, "2026-11-20"))

    def test_marks_refresh_from_current_run_as_success(self):
        status = {
            "run_id": "123", "generated_at": "2026-11-17T01:00:00Z",
            "update_detection": "fhsc_latest_statements_limit_1",
            "counts": {"updated": 1, "unchanged": 99},
        }
        summary = fundamental_refresh_summary(status, "123", degraded=False)
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["counts"]["updated"], 1)
        self.assertEqual(
            summary["update_detection"], "fhsc_latest_statements_limit_1"
        )

    def test_cached_run_does_not_report_previous_refresh_as_current(self):
        status = {
            "run_id": "previous", "generated_at": "2026-11-16T01:00:00Z",
            "update_detection": "fhsc_latest_statements_limit_1",
            "counts": {"updated": 89, "failed_preserved": 11},
        }
        summary = fundamental_refresh_summary(status, "current", degraded=False)
        self.assertEqual(summary["status"], "cache_reused")
        self.assertEqual(summary["counts"]["updated"], 0)
        self.assertEqual(summary["counts"]["failed_preserved"], 0)
        self.assertEqual(summary["last_refresh_counts"]["updated"], 89)
        self.assertEqual(summary["source_run_id"], "previous")

    def test_legacy_status_without_run_id_is_cache_reused(self):
        summary = fundamental_refresh_summary(
            {"counts": {"updated": 89}}, "current", degraded=False
        )
        self.assertEqual(summary["status"], "cache_reused")
        self.assertIsNone(summary["source_run_id"])


if __name__ == "__main__":
    unittest.main()
