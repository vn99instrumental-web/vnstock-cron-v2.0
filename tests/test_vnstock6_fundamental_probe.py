import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vnstock6_native_pipeline as pipeline
from vnstock6_fundamental_probe import latest_income_statement_probe


class FundamentalProbeTest(unittest.TestCase):
    def test_fetches_only_latest_income_statement_page(self):
        source = MagicMock()
        source.raw.return_value = [MagicMock(body={"data": [{
            "year": 2026, "quarter": 3, "values": {"revenue": 123},
        }]})]
        with patch("vnstock6_fundamental_probe.oapi.source", return_value=source) as factory:
            result = latest_income_statement_probe("FPT", "fhsc")
        factory.assert_called_once_with("fhsc")
        source.raw.assert_called_once_with(
            "financial-statement/statement",
            only_page=1,
            symbol="FPT",
            type="income-statement",
            period="quarterly",
            limit=1,
        )
        self.assertEqual(result["period"], "2026-Q3")
        self.assertEqual(result["rows"], 1)
        self.assertEqual(len(result["signature"]), 64)

    def test_materializes_full_statements_only_after_probe_changes(self):
        config = {
            "sources": {"reference": "ssi", "fundamental": "fhsc"},
            "universe": ["FPT"],
            "fundamental_refresh": {"max_workers": 1},
        }
        previous = {
            "latest_income_signature": "old", "fundamental": 0.4,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
        calculated = {
            "fundamental": 0.6, "growth": 0.3,
            "statement_signature": "new-full", "statements": {},
        }
        reference = pd.DataFrame({"symbol": ["FPT"], "industry": ["Technology"]})
        with patch.object(pipeline, "load_fundamental_cache", return_value={"FPT": previous}), patch.object(
            pipeline, "Reference"
        ) as reference_factory, patch.object(
            pipeline, "latest_income_statement_probe",
            return_value={"signature": "new", "period": "2026-Q4", "rows": 1},
        ), patch.object(
            pipeline, "fundamental_factors", return_value=calculated
        ) as materialize, patch.object(
            pipeline, "save_fundamental_cache"
        ) as save, patch.object(Path, "mkdir"), patch.object(Path, "write_text"):
            reference_factory.return_value.equity.list.return_value = reference
            status = pipeline.refresh_fundamental_cache(config, check_updates=True)
        self.assertEqual(status["counts"]["updated"], 1)
        materialize.assert_called_once_with("FPT", "fhsc", "Technology")
        saved = save.call_args.args[1]["FPT"]
        self.assertEqual(saved["fundamental"], 0.6)
        self.assertEqual(saved["latest_income_signature"], "new")
        self.assertEqual(saved["latest_income_period"], "2026-Q4")

    def test_probe_failure_preserves_cache_without_full_download(self):
        config = {
            "sources": {"reference": "ssi", "fundamental": "fhsc"},
            "universe": ["FPT"],
            "fundamental_refresh": {"max_workers": 1},
        }
        previous = {
            "latest_income_signature": "old", "fundamental": 0.4,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
        reference = pd.DataFrame({"symbol": ["FPT"], "industry": ["Technology"]})
        with patch.object(pipeline, "load_fundamental_cache", return_value={"FPT": previous}), patch.object(
            pipeline, "Reference"
        ) as reference_factory, patch.object(
            pipeline, "latest_income_statement_probe",
            return_value={"error": {"type": "RateLimitError", "code": "RATE_LIMIT"}},
        ), patch.object(
            pipeline, "fundamental_factors"
        ) as materialize, patch.object(
            pipeline, "save_fundamental_cache"
        ), patch.object(Path, "mkdir"), patch.object(Path, "write_text"), patch.object(
            pipeline.time, "sleep"
        ):
            reference_factory.return_value.equity.list.return_value = reference
            status = pipeline.refresh_fundamental_cache(config, check_updates=True)
        self.assertEqual(status["counts"]["failed_preserved"], 1)
        materialize.assert_not_called()

    def test_empty_probe_response_is_an_error(self):
        source = MagicMock()
        source.raw.return_value = [MagicMock(body={"data": []})]
        with patch("vnstock6_fundamental_probe.oapi.source", return_value=source):
            result = latest_income_statement_probe("FPT", "fhsc")
        self.assertEqual(result["error"]["type"], "ValueError")


if __name__ == "__main__":
    unittest.main()
