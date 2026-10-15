import copy
import unittest

from scripts.materialize_shadow_scoring import materialize_shadow_row


def parent_row(**overrides):
    row = {
        "symbol": "AAA",
        "scoring_version": "v4.18",
        "_regime": "UPTREND",
        "_regime_raw": "UPTREND",
        "_regime_divergence": False,
        "regime_v42": "UPTREND",
        "score_trade": 99,
        "total_score": 99,
        "score_hold": 12.5,
        "decision": "STRONG BUY",
        "confidence": "HIGH",
        "confidence_pct": 100,
        "trade_mean_reversion_norm": 0.4,
        "trade_breakout_norm": 0.4,
        "trade_flow_norm": 0.4,
        "trade_fundamental_norm": 0.4,
        "trade_growth_norm": 0.4,
        "trade_context_norm": -1.0,
        "confluence_bonus": 5,
        "n_supergroups_aligned": 3,
        "ff_intra_flag_pts": 3,
        "of_bp_pts": 4,
        "score_trade_nomr": 88,
        "decision_nomr": "BUY",
    }
    row.update(overrides)
    return row


class ShadowMaterializerTests(unittest.TestCase):
    def test_ic_weighted_core_and_scaled_threshold(self):
        shadow = materialize_shadow_row(parent_row())
        self.assertEqual(shadow["scoring_version"], "v4.19-shadow")
        self.assertEqual(shadow["score_trade"], 37.0)
        self.assertEqual(shadow["total_score"], 37.0)
        self.assertEqual(shadow["decision"], "BUY")
        self.assertEqual(shadow["_w_regime"], 0.925)
        self.assertEqual(shadow["score_hold"], 12.5)
        self.assertEqual(shadow["shadow_parent_version"], "v4.18")
        self.assertEqual(shadow["shadow_method"], "ic_shrunk_fixed_core")
        self.assertEqual(shadow["shadow_weight_profile"], "mr5_bo15_flow20_fund25_growth35")
        self.assertTrue(shadow["shadow_core_only"])

    def test_extras_are_not_used_and_stale_alternatives_are_removed(self):
        base = parent_row(confluence_bonus=100, ff_intra_flag_pts=100, of_bp_pts=100)
        shadow = materialize_shadow_row(base)
        self.assertEqual(shadow["score_trade"], 37.0)
        self.assertEqual(shadow["confluence_bonus"], 0)
        self.assertEqual(shadow["n_supergroups_aligned"], 0)
        self.assertNotIn("score_trade_nomr", shadow)
        self.assertNotIn("decision_nomr", shadow)

    def test_parent_is_not_mutated(self):
        parent = parent_row()
        before = copy.deepcopy(parent)
        materialize_shadow_row(parent)
        self.assertEqual(parent, before)

    def test_recovery_buy_caps_high_confidence(self):
        shadow = materialize_shadow_row(parent_row(
            _regime="RECOVERY",
            regime_v42="RECOVERY",
            trade_mean_reversion_norm=1,
            trade_breakout_norm=1,
            trade_flow_norm=1,
            trade_fundamental_norm=1,
            trade_growth_norm=1,
        ))
        self.assertEqual(shadow["decision"], "STRONG BUY")
        self.assertTrue(shadow["recovery_warn"])
        self.assertEqual(shadow["confidence"], "MEDIUM")
        self.assertLess(shadow["confidence_pct"], 80)

    def test_rejects_wrong_parent_and_missing_factor(self):
        with self.assertRaisesRegex(ValueError, "shadow parent"):
            materialize_shadow_row(parent_row(scoring_version="v4.17"))
        bad = parent_row()
        bad.pop("trade_flow_norm")
        with self.assertRaisesRegex(ValueError, "trade_flow_norm"):
            materialize_shadow_row(bad)


if __name__ == "__main__":
    unittest.main()
