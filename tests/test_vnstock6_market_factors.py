import unittest
from datetime import date
from unittest.mock import patch
from scripts.vnstock6_market_factors import fetch_symbol,foreign_score,proprietary_score,insider_score,order_flow_score

class MarketFactorTest(unittest.TestCase):
    def test_intraday_skips_daily_fhsc_endpoints(self):
        class Equity:
            def active_session(self): return []
            def order_book(self): return []
            def foreign_flow(self, **kwargs): return []
            def proprietary_flow(self, **kwargs): return []
            def insider_deal(self): return []
        with patch("scripts.vnstock6_market_factors.Market") as market:
            market.return_value.equity.return_value=Equity()
            live=fetch_symbol("FPT",date(2026,11,16),True)
            daily=fetch_symbol("FPT",date(2026,11,16),False)
        self.assertEqual(set(live["endpoint_rows"]),{"active_flow","order_book"})
        self.assertEqual(set(daily["endpoint_rows"]),{"foreign","proprietary","insider"})


    def test_foreign_flow_uses_legacy_deadband_and_renormalization(self):
        rows=[{"foreign_buy_value":100.0,"foreign_sell_value":20.0,"net_value":80.0} for _ in range(20)]
        score,raw=foreign_score(rows)
        self.assertEqual(score,4)
        self.assertGreater(raw["foreign_intensity"],.3)
    def test_proprietary_and_insider_scores_match_v4_spans(self):
        score,_=proprietary_score([{"net_value":float(index)*1_000_000_000} for index in range(1,21)])
        self.assertEqual(score,3)
        insider,_=insider_score([{"transaction_type":"Mua"} for _ in range(3)])
        self.assertEqual(insider,2)
    def test_active_flow_is_observed_but_not_mislabeled_phasefix(self):
        score,raw=order_flow_score([{"active_buy_volume":800,"active_sell_volume":200,"buy_order_count":8,"sell_order_count":2}],"10:00")
        self.assertEqual(score,4)
        self.assertEqual(raw["average_trade_size"],100)

if __name__ == "__main__": unittest.main()