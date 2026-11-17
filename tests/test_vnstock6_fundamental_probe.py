import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vnstock6_native_pipeline as pipeline
from vnstock6_fundamental_probe import STATEMENT_TYPES, latest_statement_probe


def probe_result(signature: str = "combined") -> dict:
    periods = {statement: "2026-Q4" for statement in STATEMENT_TYPES}
    signatures = {statement: f"{statement}-signature" for statement in STATEMENT_TYPES}
    return {
        "signature": signature,
        "period": periods["income-statement"],
        "periods": periods,
        "statement_signatures": signatures,
        "rows": len(STATEMENT_TYPES),
        "statement_types": list(STATEMENT_TYPES),
        "request_count": len(STATEMENT_TYPES),
    }


class FundamentalProbeTest(unittest.TestCase):
    def test_fetches_latest_page_for_all_statement_sets(self):
        source = MagicMock()
        source.raw.side_effect = [
            [MagicMock(body={"data": [{"year": 2026, "quarter": 3, "value": statement}]})]
            for statement in STATEMENT_TYPES
        ]
        with patch("vnstock6_fundamental_probe.oapi.source", return_value=source) as factory:
            result = latest_statement_probe("FPT", "fhsc")
        factory.assert_called_once_with("fhsc")
        self.assertEqual(source.raw.call_count, len(STATEMENT_TYPES))
        self.assertEqual(
            source.raw.call_args_list,
            [
                call(
                    "financial-statement/statement",
                    only_page=1,
                    symbol="FPT",
                    type=statement,
                    period="quarterly",
                    limit=1,
                )
                for statement in STATEMENT_TYPES
            ],
        )
        self.assertEqual(result["period"], "2026-Q3")
        self.assertEqual(result["rows"], 3)
        self.assertEqual(result["request_count"], 3)
        self.assertEqual(len(result["signature"]), 64)
        self.assertEqual(set(result["statement_signatures"]), set(STATEMENT_TYPES))

    def test_composite_signature_detects_non_income_change(self):
        def calculate(cash_value: int) -> str:
            source = MagicMock()
            source.raw.side_effect = [
                [MagicMock(body={"data": [{"year": 2026, "quarter": 3, "value": 1}]})],
                [MagicMock(body={"data": [{"year": 2026, "quarter": 3, "value": 2}]})],
                [MagicMock(body={"data": [{"year": 2026, "quarter": 3, "value": cash_value}]})],
            ]
            with patch("vnstock6_fundamental_probe.oapi.source", return_value=source):
                return latest_statement_probe("FPT", "fhsc")["signature"]

        self.assertNotEqual(calculate(3), calculate(4))

    def test_materializes_full_statements_only_after_probe_changes(self):
        config = {
            "sources": {"reference": "ssi", "fundamental": "fhsc"},
            "universe": ["FPT"],
            "fundamental_refresh": {"max_workers": 1},
        }
        previous = {
            "latest_statement_signature": "old", "fundamental": 0.4,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
        calculated = {
            "fundamental": 0.6, "growth": 0.3,
            "statement_signature": "new-full", "statements": {},
        }
        reference = pd.DataFrame({"symbol": ["FPT"], "industry": ["Technology"]})
        result = probe_result("new")
        with patch.object(pipeline, "load_fundamental_cache", return_value={"FPT": previous}), patch.object(
            pipeline, "Reference"
        ) as reference_factory, patch.object(
            pipeline, "latest_statement_probe", return_value=result,
        ), patch.object(
            pipeline, "fundamental_factors", return_value=calculated
        ) as materialize, patch.object(
            pipeline, "save_fundamental_cache"
        ) as save, patch.object(Path, "mkdir"), patch.object(Path, "write_text"):
            reference_factory.return_value.equity.list.return_value = reference
            status = pipeline.refresh_fundamental_cache(config, check_updates=True)
        self.assertEqual(status["counts"]["updated"], 1)
        self.assertEqual(status["update_detection"], "fhsc_latest_statements_limit_1")
        self.assertEqual(status["probe_request_count"], 3)
        materialize.assert_called_once_with("FPT", "fhsc", "Technology")
        saved = save.call_args.args[1]["FPT"]
        self.assertEqual(saved["fundamental"], 0.6)
        self.assertEqual(saved["latest_statement_signature"], "new")
        self.assertEqual(saved["latest_income_signature"], "income-statement-signature")
        self.assertEqual(saved["latest_income_period"], "2026-Q4")

    def test_probe_failure_preserves_cache_without_full_download(self):
        config = {
            "sources": {"reference": "ssi", "fundamental": "fhsc"},
            "universe": ["FPT"],
            "fundamental_refresh": {"max_workers": 1},
        }
        previous = {
            "latest_statement_signature": "old", "fundamental": 0.4,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
        reference = pd.DataFrame({"symbol": ["FPT"], "industry": ["Technology"]})
        with patch.object(pipeline, "load_fundamental_cache", return_value={"FPT": previous}), patch.object(
            pipeline, "Reference"
        ) as reference_factory, patch.object(
            pipeline, "latest_statement_probe",
            return_value={"error": {"type": "RateLimitError", "code": "RATE_LIMIT"}, "request_count": 1},
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
        self.assertEqual(status["probe_request_count"], 3)
        materialize.assert_not_called()

    def test_empty_probe_response_is_an_error(self):
        source = MagicMock()
        source.raw.return_value = [MagicMock(body={"data": []})]
        with patch("vnstock6_fundamental_probe.oapi.source", return_value=source):
            result = latest_statement_probe("FPT", "fhsc")
        self.assertEqual(result["error"]["type"], "ValueError")
        self.assertEqual(result["request_count"], 1)


if __name__ == "__main__":
    unittest.main()
