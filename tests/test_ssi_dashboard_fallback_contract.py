import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SSI_HISTORY = ROOT / "output" / "serving" / "ssi" / "current" / "history" / "ssi-v4.18-independent.json"
GEN6_HISTORY = ROOT / "output" / "serving" / "vnstock6" / "current" / "history" / "v6.4.18.json"
SSI_SOURCE = ROOT / "web" / "lib" / "data-source" / "ssi-serving.ts"
SSI_UI = ROOT / "web" / "components" / "ssi-aligned-dashboard.tsx"
TABLE = ROOT / "web" / "components" / "signals-table.tsx"


class SsiDashboardFallbackContractTests(unittest.TestCase):
    def test_current_history_can_be_composed_without_backfill(self):
        ssi_rows = json.loads(SSI_HISTORY.read_text(encoding="utf-8"))["rows"]
        gen6_rows = json.loads(GEN6_HISTORY.read_text(encoding="utf-8"))["rows"]
        native_keys = {(row["signal_date"], row["symbol"]) for row in ssi_rows}
        fallback = {}
        for row in gen6_rows:
            key = (row.get("signal_date"), row.get("symbol"))
            if key in native_keys:
                continue
            previous = fallback.get(key)
            if previous is None or str(row.get("snap_time") or "") >= str(previous.get("snap_time") or ""):
                fallback[key] = row
        self.assertTrue(native_keys)
        self.assertTrue(fallback)
        self.assertTrue(native_keys.isdisjoint(fallback))

    def test_fallback_is_history_only_and_keeps_gen6_provenance(self):
        source = SSI_SOURCE.read_text(encoding="utf-8")
        history_block = source[source.index("async history("):source.index("async analysis(")]
        self.assertIn("gen6HistoryFallback(nativeKeys)", history_block)
        self.assertIn('display_source: "gen6_fallback"', source)
        self.assertIn('calculation_engine: "gen6"', source)
        self.assertIn('scoring_version: SSI_HISTORY_FALLBACK_VERSION', source)
        self.assertIn("nativeKeys.has(key)", source)
        self.assertNotIn("gen6HistoryFallback", source[source.index("async today("):source.index("async history(")])
        self.assertNotIn("gen6HistoryFallback", source[source.index("async analysis("):])

    def test_ui_labels_fallback_and_does_not_claim_ssi_ic(self):
        ui = SSI_UI.read_text(encoding="utf-8")
        table = TABLE.read_text(encoding="utf-8")
        self.assertIn("Lịch sử tham chiếu Gen 6", ui)
        self.assertIn("không tham gia score hoặc IC của SSI", ui)
        self.assertIn("Gen 6 lịch sử", table)
        self.assertIn('dashboard.ic[`ret_${horizon}d`]', ui)


if __name__ == "__main__":
    unittest.main()
