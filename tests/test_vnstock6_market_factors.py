import unittest
from datetime import date
from unittest.mock import patch

from scripts.vnstock6_market_factors import (
    average_trade_size,
    fetch_symbol,
    foreign_score,
    insider_score,
    proprietary_score,
    session_turnover_value,
)


class MarketFactorTest(unittest.TestCase):
    def test_foreign_flow_uses_v4_bands(self):
        rows = [
            {"foreign_buy_value": 100.0, "foreign_sell_value": 20.0, "foreign_net_value": 80.0}
            for _ in range(20)
        ]
        score, raw = foreign_score(rows)
        self.assertEqual(score, 4)
        self.assertGreater(raw["foreign_intensity"], 0.3)
        self.assertEqual(raw["foreign_net_1d"], 80.0)

    def test_proprietary_flow_uses_existing_v4_bands(self):
        rows = [{"net_value": 1_500_000_000.0} for _ in range(10)]
        score, raw = proprietary_score(rows)
        self.assertEqual(score, 2)
        self.assertEqual(raw["proprietary_net_5d"], 7_500_000_000.0)

    def test_insider_flow_uses_existing_v4_counts(self):
        score, raw = insider_score([
            {"transaction_type": "Mua"},
            {"transaction_type": "buy"},
            {"transaction_type": "sell"},
        ])
        self.assertEqual(score, 1)
        self.assertEqual(raw, {"insider_buy_count": 2, "insider_sell_count": 1})


    def test_average_trade_size_uses_ssi_session_totals(self):
        rows = [{
            "total_buy_trade_volume": 800,
            "total_sell_trade_volume": 200,
            "total_buy_trade": 8,
            "total_sell_trade": 2,
        }]
        self.assertEqual(average_trade_size(rows), 100)
        self.assertEqual(session_turnover_value([{"total_value": 12_345_000_000}]), 12_345_000_000)

    def test_daily_mode_skips_depth_calls_and_preserves_session_cache(self):
        class Equity:
            def foreign_flow(self, **kwargs):
                return [{"foreign_buy_value": 100, "foreign_sell_value": 20}] * 20
            def session_stats(self, **kwargs):
                raise AssertionError("daily must not fetch session depth")
            def active_session(self, **kwargs):
                raise AssertionError("daily must not fetch active session")
            def order_book(self, **kwargs):
                raise AssertionError("daily must not fetch order book")

        class Factory:
            def equity(self, symbol): return Equity()

        cache = {
            "s_depth_wall": 2, "depth_signal_date": "2026-11-16",
            "depth_snap_time": "14:19", "depth_captured_at": "2026-11-16T07:19:00Z",
        }
        with patch("scripts.vnstock6_market_factors.Market", return_value=Factory()):
            result = fetch_symbol("FPT", date(2026, 11, 16), cache, fetch_depth=False)
        self.assertEqual(result["s_depth_wall"], 2)
        self.assertEqual(result["depth_snap_time"], "14:19")
        self.assertEqual(result["endpoint_rows"]["order_book"], 0)

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


    def test_intraday_preserves_slow_cache_without_calling_slow_endpoints(self):
        class Equity:
            def foreign_flow(self, **kwargs): return [{"foreign_buy_value": 100, "foreign_sell_value": 20, "foreign_net_value": 80}] * 20
            def session_stats(self, **kwargs): return [{"total_buy_trade_volume": 800, "total_sell_trade_volume": 200, "total_buy_trade": 8, "total_sell_trade": 2}]
            def order_book(self, **kwargs): return []
            def proprietary_flow(self, **kwargs): raise AssertionError("slow endpoint called during intraday")
            def insider_deal(self, **kwargs): raise AssertionError("slow endpoint called during intraday")

        class Factory:
            def equity(self, symbol): return Equity()

        cache = {
            "s_prop_5d": -3, "s_insider": 2,
            "raw": {"proprietary_net_5d": -6_000_000_000, "insider_buy_count": 3, "insider_sell_count": 0},
        }
        with patch("scripts.vnstock6_market_factors.Market", return_value=Factory()):
            result = fetch_symbol("FPT", date(2026, 11, 16), cache, refresh_slow=False)
        self.assertEqual(result["s_prop_5d"], -3)
        self.assertEqual(result["s_insider"], 2)
        self.assertEqual(result["endpoint_sources"]["proprietary_flow"], "FHSC_CACHE")

    def test_daily_refresh_replaces_slow_cache(self):
        class Equity:
            def foreign_flow(self, **kwargs): return []
            def session_stats(self, **kwargs): return []
            def active_session(self, **kwargs): return []
            def order_book(self, **kwargs): return []
            def proprietary_flow(self, **kwargs): return [{"net_value": 1_500_000_000.0}] * 10
            def insider_deal(self, **kwargs): return [{"transaction_type": "Mua"}] * 3

        class Factory:
            def equity(self, symbol): return Equity()

        with patch("scripts.vnstock6_market_factors.Market", return_value=Factory()):
            result = fetch_symbol("FPT", date(2026, 11, 16), {}, refresh_slow=True)
        self.assertEqual(result["s_prop_5d"], 2)
        self.assertEqual(result["s_insider"], 2)
        self.assertEqual(result["endpoint_sources"]["proprietary_flow"], "FHSC")


if __name__ == "__main__":
    unittest.main()
