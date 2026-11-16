import unittest
from datetime import date
from unittest.mock import patch

from scripts.vnstock6_market_factors import average_trade_size, fetch_symbol, foreign_score


class MarketFactorTest(unittest.TestCase):
    def test_foreign_flow_uses_v4_bands(self):
        rows = [
            {"foreign_buy_value": 100.0, "foreign_sell_value": 20.0, "foreign_net_value": 80.0}
            for _ in range(20)
        ]
        score, raw = foreign_score(rows)
        self.assertEqual(score, 4)
        self.assertGreater(raw["foreign_intensity"], 0.3)

    def test_average_trade_size_uses_ssi_session_totals(self):
        rows = [{
            "total_buy_trade_volume": 800,
            "total_sell_trade_volume": 200,
            "total_buy_trade": 8,
            "total_sell_trade": 2,
        }]
        self.assertEqual(average_trade_size(rows), 100)

    def test_foreign_falls_back_and_depth_uses_fhsc_book(self):
        class Equity:
            def __init__(self, source):
                self.source = source

            def foreign_flow(self, **kwargs):
                if self.source == "ssi":
                    raise RuntimeError("ssi unavailable")
                return [
                    {"foreign_buy_value": 100, "foreign_sell_value": 20, "foreign_net_value": 80}
                ] * 20

            def session_stats(self, **kwargs):
                return [{
                    "total_buy_trade_volume": 800, "total_sell_trade_volume": 200,
                    "total_buy_trade": 8, "total_sell_trade": 2,
                }]

            def active_session(self, **kwargs):
                return []

            def order_book(self, **kwargs):
                return [{
                    "bid_price_1": 100, "bid_volume_1": 5000,
                    "ask_price_1": 101, "ask_volume_1": 1000,
                }]

        class Factory:
            def __init__(self, source):
                self.source = source

            def equity(self, symbol):
                return Equity(self.source)

        with patch("scripts.vnstock6_market_factors.Market", side_effect=lambda source: Factory(source)):
            result = fetch_symbol("FPT", date(2026, 11, 16))
        self.assertEqual(result["endpoint_sources"]["foreign_flow"], "FHSC")
        self.assertEqual(result["endpoint_sources"]["trade_size"], "SSI")
        self.assertEqual(result["endpoint_sources"]["order_book"], "FHSC")
        self.assertEqual(result["s_ff_net"], 4)
        self.assertEqual(result["raw"]["average_trade_size"], 100)


if __name__ == "__main__":
    unittest.main()
