import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "n8n" / "shared-raw-ssi-fhsc-schedule.json"


class N8nScheduleContractTests(unittest.TestCase):
    def test_cadences_dispatch_only_shared_raw_workflow(self):
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
            node = nodes[f"Dispatch shared raw {cadence}"]
            params = node["parameters"]
            self.assertEqual(params["method"], "POST")
            self.assertTrue(params["url"].endswith("/shared_raw_ssi_fhsc.yml/dispatches"))
            self.assertEqual(json.loads(params["body"]), {
                "ref": "main", "inputs": {"cadence": cadence},
            })
            self.assertNotIn("credentials", node)
            self.assertNotIn("token", json.dumps(node).lower())


    def test_legacy_gen6_dispatches_redirect_to_shared_raw(self):
        expected = {
            "vnstock6_native_production.yml": "cadence=intraday",
            "vnstock6_daily_maintenance.yml": "cadence=daily",
            "vnstock6_fundamental_refresh.yml": "cadence=weekly",
        }
        for filename, cadence in expected.items():
            text = (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
            self.assertIn("redirect_legacy_schedule:", text)
            self.assertIn("if: inputs.raw_release_id == ''", text)
            self.assertIn("shared_raw_ssi_fhsc.yml --ref main -f " + cadence, text)
            self.assertIn("actions: write", text)
            self.assertIn("GH_REPO: ${{ github.repository }}", text)

    def test_shared_collector_dispatches_with_explicit_repo(self):
        text = (
            ROOT / ".github" / "workflows" / "shared_raw_ssi_fhsc.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("GH_REPO: ${{ github.repository }}", text)

    def test_ssi_consumer_has_independent_concurrency_queue(self):
        shared_raw = (ROOT / ".github" / "workflows" / "shared_raw_ssi_fhsc.yml").read_text(encoding="utf-8")
        ssi = (ROOT / ".github" / "workflows" / "ssi_independent_production.yml").read_text(encoding="utf-8")
        self.assertIn("group: ssi-main-writer", ssi)
        self.assertIn("group: vnstock-main-writer", shared_raw)
        self.assertIn("cancel-in-progress: false", ssi)
        self.assertIn("python -m scripts.ssi_raw_features", ssi)
        self.assertIn("python -m scripts.ssi_independent_pipeline build", ssi)
        self.assertNotIn(" collect --cadence ", ssi)
        self.assertNotIn("gh workflow run shared_raw_ssi_fhsc.yml", ssi)


if __name__ == "__main__":
    unittest.main()
