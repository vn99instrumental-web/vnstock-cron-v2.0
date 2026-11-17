import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_vnstock6_candidate import fundamental_refresh_summary


class FundamentalRefreshSummaryTest(unittest.TestCase):
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
