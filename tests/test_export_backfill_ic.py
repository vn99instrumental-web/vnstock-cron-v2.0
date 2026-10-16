import unittest

from scripts.export_backfill_ic_to_supabase import build_backfill_sample, compute_backfill_rows


def prediction(day: str, symbol: str, source_id: str, shadow_id: str) -> dict:
    value = float(ord(symbol[-1]) - ord("A") + 1)
    return {
        "pred_id": shadow_id,
        "scoring_version": "v4.19-shadow",
        "signal_date": day,
        "symbol": symbol,
        "snap_time": "14:45",
        "shadow_data_origin": "retrospective_backfill",
        "shadow_forward_eligible": False,
        "shadow_backfill_source_pred_id": source_id,
        "score_trade": value,
        "trade_mean_reversion_norm": value,
        "trade_breakout_norm": value,
        "trade_flow_norm": value,
        "trade_fundamental_norm": value,
        "trade_growth_norm": value,
        "trade_context_norm": value,
    }


class BackfillICTests(unittest.TestCase):
    def setUp(self):
        self.preds = []
        self.outs = []
        for day_index, day in enumerate(("2026-09-01", "2026-09-02", "2026-09-03")):
            for index, symbol in enumerate(("AAA", "AAB", "AAC", "AAD", "AAE"), start=1):
                source_id = f"src-{day}-{symbol}"
                shadow_id = f"shadow-{day}-{symbol}"
                self.preds.append(prediction(day, symbol, source_id, shadow_id))
                self.outs.append({
                    "pred_id": source_id,
                    "scoring_version": "v4.18",
                    "lens": "trade",
                    "ret_1d": index + day_index,
                    "ret_3d": index + day_index,
                    "ret_5d": index + day_index,
                    "ret_10d": index + day_index,
                })

    def test_maps_source_outcome_without_creating_forward_outcome(self):
        preds, outs = build_backfill_sample(self.preds, self.outs)
        self.assertEqual(len(preds), 15)
        self.assertEqual(len(outs), 15)
        self.assertTrue(all(out["pred_id"].startswith("shadow-") for out in outs))
        self.assertTrue(all(out["scoring_version"] == "v4.19-shadow" for out in outs))

    def test_computes_separate_historical_factor_rows(self):
        rows = compute_backfill_rows(self.preds, self.outs)
        self.assertEqual(len(rows), 28)
        self.assertTrue(all(row["sample_kind"] == "retrospective_backfill" for row in rows))
        self.assertTrue(all(row["source_version"] == "v4.18" for row in rows))
        score_5d = next(row for row in rows if row["factor"] == "score_trade" and row["horizon"] == 5)
        self.assertEqual(score_5d["n"], 15)
        self.assertAlmostEqual(score_5d["ic"], 1.0)


if __name__ == "__main__":
    unittest.main()
