import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "n8n" / "shared-raw-ssi-fhsc-schedule.json"
UNIFIED = ROOT / ".github" / "workflows" / "shared_raw_ssi_fhsc.yml"


class N8nScheduleContractTests(unittest.TestCase):
    def test_cadences_dispatch_only_unified_workflow(self):
        value = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        self.assertFalse(value["active"])
        self.assertEqual(value["settings"]["timezone"], "Asia/Ho_Chi_Minh")
        nodes = {node["name"]: node for node in value["nodes"]}
        expected = {
            "Intraday ICT weekdays": [
                "25 9 * * 1-5", "25 10 * * 1-5", "25 11 * * 1-5",
                "25 13 * * 1-5", "25 14 * * 1-5",
            ],
            "Daily ICT weekdays": ["5 15 * * 1-5"],
            "Weekly ICT Sunday": ["15 7 * * 0"],
        }
        for name, expressions in expected.items():
            actual = [item["expression"] for item in nodes[name]["parameters"]["rule"]["interval"]]
            self.assertEqual(actual, expressions)
        for cadence in ("intraday", "daily", "weekly"):
            node = nodes[f"Dispatch unified {cadence}"]
            params = node["parameters"]
            self.assertEqual(params["method"], "POST")
            self.assertTrue(params["url"].endswith("/shared_raw_ssi_fhsc.yml/dispatches"))
            self.assertEqual(json.loads(params["body"]), {
                "ref": "main", "inputs": {"cadence": cadence, "engine": "both"},
            })
            self.assertNotIn("credentials", node)
            self.assertNotIn("token", json.dumps(node).lower())

    def test_canonical_n8n_does_not_reference_legacy_workflows(self):
        export = WORKFLOW.read_text(encoding="utf-8")
        for filename in (
            "vnstock6_native_production.yml",
            "vnstock6_daily_maintenance.yml",
            "vnstock6_fundamental_refresh.yml",
            "ssi_independent_production.yml",
        ):
            self.assertNotIn(filename, export)
            workflow = (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
            self.assertNotIn("\n  schedule:", workflow)

    def test_unified_workflow_does_not_dispatch_calculator_runs(self):
        text = UNIFIED.read_text(encoding="utf-8")
        self.assertIn("name: Unified SSI FHSC data production", text)
        self.assertIn("raw_release_id:", text)
        self.assertIn("options: [both, gen6, ssi]", text)
        self.assertNotIn("gh workflow run", text)
        self.assertNotIn("actions: write", text)
        self.assertEqual(text.count("Revalidate dashboard once"), 1)
        self.assertLess(text.index("Persist provider raw before any calculation"), text.index("Calculate Gen 6 from stored raw"))
        self.assertLess(text.index("Calculate Gen 6 from stored raw"), text.index("Calculate SSI from the same stored raw"))

    def test_calculators_share_one_raw_release_and_separate_storage(self):
        text = UNIFIED.read_text(encoding="utf-8")
        self.assertIn('RAW_RELEASE_ID: ${{ steps.release.outputs.release_id }}', text)
        self.assertIn("git add -- output/history/vnstock6", text)
        self.assertIn("git add -- output/history/ssi-independent output/serving/ssi", text)
        self.assertIn("steps.gen6.outcome == 'success'", text)
        self.assertIn("steps.ssi.outcome == 'success'", text)
        self.assertIn("continue-on-error: true", text)

    def test_manual_ssi_retry_uses_serialized_writer_and_never_collects(self):
        ssi = (ROOT / ".github" / "workflows" / "ssi_independent_production.yml").read_text(encoding="utf-8")
        self.assertIn("group: vnstock-main-writer", ssi)
        self.assertIn("cancel-in-progress: false", ssi)
        self.assertIn("python -m scripts.ssi_raw_features", ssi)
        self.assertIn("python -m scripts.ssi_independent_pipeline build", ssi)
        self.assertNotIn(" collect --cadence ", ssi)
        self.assertNotIn("gh workflow run shared_raw_ssi_fhsc.yml", ssi)


if __name__ == "__main__":
    unittest.main()
