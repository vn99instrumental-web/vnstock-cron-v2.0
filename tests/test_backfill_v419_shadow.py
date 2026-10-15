import unittest

from scripts.backfill_v419_shadow import ENTRY_FIELDS, select_backfill_rows
from tests.test_materialize_shadow_scoring import parent_row


class BackfillV419Tests(unittest.TestCase):
    def test_keeps_daily_close_and_latest_buy_without_entry_levels(self):
        rows = []
        for symbol in ("AAA", "BBB"):
            rows.append(parent_row(symbol=symbol, signal_date="2026-10-14", snap_time="10:00", pred_id=f"{symbol}-10", entry=10, stop=9, tp1=12))
            rows.append(parent_row(
                symbol=symbol, signal_date="2026-10-14", snap_time="11:00", pred_id=f"{symbol}-11",
                trade_mean_reversion_norm=-1, trade_breakout_norm=-1, trade_flow_norm=-1,
                trade_fundamental_norm=-1, trade_growth_norm=-1, entry=11, stop=10, tp1=13,
            ))
            rows.append(parent_row(symbol=symbol, signal_date="2026-10-15", snap_time="09:00", pred_id=f"{symbol}-forward"))

        result = select_backfill_rows(rows, "2026-10-15")
        self.assertEqual(len(result), 4)
        self.assertEqual({row["snap_time"] for row in result}, {"10:00", "11:00"})
        self.assertTrue(all(row["scoring_version"] == "v4.19-shadow" for row in result))
        self.assertTrue(all(row["shadow_data_origin"] == "retrospective_backfill" for row in result))
        self.assertTrue(all(row["shadow_forward_eligible"] is False for row in result))
        self.assertTrue(all(row["pred_id"].endswith("_v2fv4_v4.19-shadow") for row in result))
        self.assertTrue(all(not any(field in row for field in ENTRY_FIELDS) for row in result))


if __name__ == "__main__":
    unittest.main()