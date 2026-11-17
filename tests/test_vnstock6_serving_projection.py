import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_dashboard_serving_local import _latest_day_rows, _latest_runs, _today_signal
from sync_supabase import build_run_rows


class ServingProjectionTests(unittest.TestCase):
    def test_preserves_gen6_indicators_at_serving_boundary(self):
        expected = {
            "adx": 26.0, "supertrend": 95.0, "s_trend_st": 4.0,
            "s_ff_net": None, "s_of_phasefix": None, "s_prop_5d": None,
            "s_insider": None, "s_depth_wall": None, "s_cf_core": 1.5,
        }
        row = {
            "symbol": "FPT", "scoring_version": "v6.4.18",
            "pipeline_generation": 6, "market_source": "SSI",
            "signal_date": "2026-11-13", "decision": "BUY",
            "score_trade": 25.0, "snap_time": "10:00", "price": 100.0,
            "proprietary_net_5d": 7_500_000_000.0,
            "proprietary_flow_status": "available",
            "proprietary_source": "FHSC_CACHE",
            "insider_buy_count": 2,
            "insider_sell_count": 1,
            "insider_deal_status": "available",
            "order_book_source": "FHSC_SESSION_CACHE",
            "order_flow_source": "SSI_OHLCV_PHASE_VOLUME",
            **expected,
        }

        projected = _today_signal(row, None)

        for key, value in expected.items():
            self.assertEqual(projected[key], value, key)

        breakdown = projected["breakdown"]
        self.assertEqual(breakdown["proprietary_net_5d"], 7_500_000_000.0)
        self.assertEqual(breakdown["proprietary_flow_status"], "available")
        self.assertEqual(breakdown["proprietary_source"], "FHSC_CACHE")
        self.assertEqual(breakdown["insider_buy_count"], 2)
        self.assertEqual(breakdown["insider_deal_status"], "available")
        self.assertEqual(breakdown["order_book_source"], "FHSC_SESSION_CACHE")
        self.assertEqual(breakdown["order_flow_source"], "SSI_OHLCV_PHASE_VOLUME")

    def test_gen6_run_uses_actual_execution_timestamp_and_kind(self):
        rows = build_run_rows([
            {
                "symbol": "FPT", "signal_date": "2026-11-17", "snap_time": "16:54",
                "scoring_version": "v6.4.18", "decision": "BUY",
                "snapshot_at": "2026-11-17T16:54:20+07:00",
                "run_kind": "postmarket",
            }
        ])

        self.assertEqual(rows[0]["kind"], "postmarket")
        self.assertEqual(rows[0]["started_at"], "2026-11-17T16:54:20+07:00")

    def test_timestamped_run_replaces_legacy_synthetic_eod_marker(self):
        rows = [
            {
                "symbol": "FPT", "signal_date": "2026-11-17", "snap_time": "23:59",
                "scoring_version": "v6.4.18", "decision": "BUY",
            },
            {
                "symbol": "FPT", "signal_date": "2026-11-17", "snap_time": "16:54",
                "scoring_version": "v6.4.18", "decision": "BUY",
                "snapshot_at": "2026-11-17T16:54:20+07:00",
            },
        ]
        _, latest = _latest_runs(rows, ["v6.4.18"])
        self.assertEqual(latest["v6.4.18"][0]["snap_time"], "16:54")
        day = _latest_day_rows(rows, ["v6.4.18"])
        self.assertEqual([row["snap_time"] for row in day["v6.4.18"]], ["16:54"])

if __name__ == "__main__":
    unittest.main()
