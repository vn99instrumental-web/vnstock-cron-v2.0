import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.export_ohlc_to_supabase import (
    bootstrap_local_from_supabase,
    merge_ohlc_rows,
    write_local_ohlc,
)


class LocalOHLCTests(unittest.TestCase):
    def test_incremental_rows_upsert_without_truncating_history(self):
        existing = [
            {"symbol": "SHB", "date": "2026-01-02", "close": 10.0},
            {"symbol": "SHB", "date": "2026-01-03", "close": 10.5},
        ]
        incoming = [
            {"symbol": "SHB", "date": "2026-01-03", "close": 10.7},
            {"symbol": "SHB", "date": "2026-01-04", "close": 11.0},
        ]
        merged = merge_ohlc_rows(existing, incoming, "2026-01-01")
        self.assertEqual([row["date"] for row in merged], ["2026-01-02", "2026-01-03", "2026-01-04"])
        self.assertEqual(merged[1]["close"], 10.7)

    def test_atomic_writer_applies_retention(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            count = write_local_ohlc(root, "SHB", [
                {"symbol": "SHB", "date": "2025-01-01", "close": 9.0},
                {"symbol": "SHB", "date": "2026-01-02", "close": 10.0},
            ], "2025-06-01")
            self.assertEqual(count, 1)
            content = (root / "SHB.json").read_text(encoding="utf-8")
            self.assertNotIn("2025-01-01", content)
            self.assertIn("2026-01-02", content)

    @patch("scripts.export_ohlc_to_supabase.SupabaseReader")
    def test_bootstrap_reads_retained_rows_from_supabase(self, reader_cls):
        reader_cls.return_value.rows.return_value = [
            {"symbol": "SHB", "date": "2026-01-02", "close": 10.0},
            {"symbol": "SHB", "date": "2026-01-03", "close": 10.5},
        ]
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            symbols, total = bootstrap_local_from_supabase(
                "https://example.supabase.co",
                "server-only-key",
                Path(directory),
                "2025-06-01",
            )
            self.assertEqual((symbols, total), (1, 2))
            reader_cls.return_value.rows.assert_called_once()

if __name__ == "__main__":
    unittest.main()
