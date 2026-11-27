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
                "15 9 * * 1-5", "30 10 * * 1-5", "30 11 * * 1-5",
                "45 13 * * 1-5", "50 14 * * 1-5",
            ],
            "Daily ICT weekdays": ["15 16 * * 1-5"],
            "Weekly ICT Sunday": ["15 9 * * 0"],
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


if __name__ == "__main__":
    unittest.main()