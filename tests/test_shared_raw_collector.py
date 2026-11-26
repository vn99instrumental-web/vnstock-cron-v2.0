from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from scripts import shared_raw_collector as raw

ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / ".tmp" / "shared-raw-tests"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)


class FakeTransport:
    def __init__(self, *, fail_ohlcv: set[str] | None = None):
        self.fail_ohlcv = fail_ohlcv or set()
        self.calls: list[tuple[str, str, str | None, dict]] = []

    def fetch(self, endpoint: str, source: str, symbol: str | None, parameters: dict):
        self.calls.append((endpoint, source, symbol, parameters))
        if endpoint == "ohlcv" and symbol in self.fail_ohlcv:
            raise RuntimeError("fixture transport failure containing no secret")
        if endpoint in {"ohlcv", "index_ohlcv"}:
            return [{
                "time": "2026-11-25", "open": 100, "high": 103,
                "low": 99, "close": 102, "volume": 1000,
            }]
        if endpoint == "foreign_flow":
            return [{"time": "2026-11-25", "foreign_net_value": 100_000_000}]
        if endpoint == "session_stats":
            return [{"symbol": symbol, "time": "2026-11-25", "total_value": 1_000_000_000}]
        if endpoint == "reference":
            return [{"symbol": "FPT", "industry": "Technology"}, {"symbol": "HPG", "industry": "Materials"}]
        if endpoint in {"balance_sheet", "income_statement", "cash_flow"}:
            return [{
                "report_period": "2026Q3", "item_id": f"RAW_{endpoint.upper()}",
                "item_name": endpoint, "item_unit": "VND", "item_value": 123,
            }]
        if endpoint == "order_book":
            return [{"time": "2026-11-25T15:00:00+07:00", "bid_volume_1": 10, "ask_volume_1": 8}]
        if endpoint == "proprietary_flow":
            return [{"time": "2026-11-25", "net_value": 5_000_000}]
        if endpoint == "insider_deal":
            return [{"transaction_date": "2026-11-20", "transaction_type": "buy"}]
        raise AssertionError(endpoint)


def config() -> dict:
    return {
        "schema_version": 1,
        "namespace": "ssi-fhsc-raw",
        "sources": {"market": "ssi", "fundamental": "fhsc"},
        "market_history_calendar_days": 800,
        "flow_history_calendar_days": 45,
        "minimum_ohlcv_symbols": 2,
        "max_workers": 2,
        "universe": ["FPT", "HPG"],
    }


class SharedRawCollectorTests(unittest.TestCase):
    def collect(self, root: Path, *, mode: str = "full", transport: FakeTransport | None = None):
        return raw.collect_release(
            config(),
            transport or FakeTransport(),
            root,
            mode=mode,
            signal_date=date(2026, 11, 25),
            created_at=datetime(2026, 11, 25, 9, 30, tzinfo=timezone.utc),
        )

    def test_full_release_is_immutable_hashed_and_source_explicit(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp)
            transport = FakeTransport()
            manifest = self.collect(root, transport=transport)
            release_dir = root / "releases" / manifest["release_id"]

            verified = raw.verify_release(release_dir)
            self.assertEqual(verified["qc"]["status"], "passed")
            self.assertEqual(verified["contract"]["calculated_fields"], [])
            self.assertFalse(verified["contract"]["gen6_dependency"])
            self.assertEqual(json.loads((root / "current.json").read_text())["release_id"], manifest["release_id"])
            self.assertEqual({call[1] for call in transport.calls if call[0] in {"ohlcv", "foreign_flow", "session_stats"}}, {"SSI"})
            self.assertEqual({call[1] for call in transport.calls if call[0] in {"balance_sheet", "income_statement", "cash_flow"}}, {"FHSC"})
            with self.assertRaisesRegex(FileExistsError, "IMMUTABLE"):
                self.collect(root)

    def test_market_mode_does_not_call_post_market_slow_endpoints(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            transport = FakeTransport()
            manifest = self.collect(Path(temp), mode="market", transport=transport)
            called = {call[0] for call in transport.calls}
            self.assertFalse({"order_book", "proprietary_flow", "insider_deal"} & called)
            self.assertEqual(manifest["mode"], "market")

    def test_failed_quality_gate_does_not_publish_current_pointer(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp)
            with self.assertRaisesRegex(RuntimeError, "COVERAGE_BELOW_MINIMUM"):
                self.collect(root, transport=FakeTransport(fail_ohlcv={"FPT"}))
            self.assertFalse((root / "current.json").exists())
            self.assertFalse(any((root / "releases").glob("*")) if (root / "releases").exists() else False)

    def test_tamper_is_detected_by_dataset_hash(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp)
            manifest = self.collect(root)
            release_dir = root / "releases" / manifest["release_id"]
            dataset = release_dir / "market" / "equity-ohlcv.jsonl"
            dataset.write_bytes(dataset.read_bytes() + b"{}\n")
            with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
                raw.verify_release(release_dir)

    def test_manifest_rejects_calculated_field_declaration(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp)
            manifest = self.collect(root)
            release_dir = root / "releases" / manifest["release_id"]
            path = release_dir / "manifest.json"
            changed = copy.deepcopy(manifest)
            changed["contract"]["calculated_fields"] = ["score"]
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CALCULATED_FIELDS_FORBIDDEN"):
                raw.verify_release(release_dir)

    def test_current_pointer_rejects_path_traversal_release_id(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp)
            root.mkdir(parents=True, exist_ok=True)
            (root / "current.json").write_text(json.dumps({"release_id": "../../outside"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CURRENT_RELEASE_ID_INVALID"):
                raw.load_current_manifest(root)


if __name__ == "__main__":
    unittest.main()
