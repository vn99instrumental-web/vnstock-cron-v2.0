from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from scripts import shared_raw_collector as raw
from scripts import ssi_raw_features as features


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / ".tmp" / "ssi-raw-feature-tests"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)


def statement(item: str, values: list[float]) -> list[dict]:
    periods = ["2025Q3", "2025Q4", "2026Q1", "2026Q2", "2026Q3"]
    return [{"report_period": period, "item_id": item, "item_value": value, "item_unit": "VND"} for period, value in zip(periods, values)]


class FeatureTransport:
    def fetch(self, endpoint: str, source: str, symbol: str | None, parameters: dict):
        if endpoint == "reference":
            return [{"symbol": "FPT", "industry": "Technology"}]
        if endpoint in {"ohlcv", "ohlcv_intraday", "index_ohlcv"}:
            start = date(2025, 10, 1)
            return [{
                "time": (start + timedelta(days=index)).isoformat(),
                "open": 90 + index / 10, "high": 92 + index / 10,
                "low": 89 + index / 10, "close": 91 + index / 10,
                "volume": 1_000_000 + index * 1000,
            } for index in range(300)]
        if endpoint in {"foreign_flow", "foreign_flow_fhsc"}:
            return [{"time": f"2026-11-{day:02d}", "foreign_net_value": day * 1_000_000} for day in range(1, 21)]
        if endpoint == "session_stats":
            return [{"time": "2026-11-25", "total_buy_trade_volume": 5000, "total_sell_trade_volume": 5000, "total_buy_trade": 50, "total_sell_trade": 50}]
        if endpoint == "active_session":
            return [{"active_buy_volume": 5000, "active_sell_volume": 5000, "buy_order_count": 50, "sell_order_count": 50}]
        if endpoint == "income_statement":
            return (
                statement("IS_NET_REVENUE", [100, 110, 120, 130, 125])
                + statement("IS_GROSS_PROFIT", [40, 44, 48, 52, 50])
                + statement("IS_NET_PROFIT_AFTER_TAX", [10, 11, 12, 13, 15])
                + [{"report_period": "2027Q1", "item_id": "IS_NET_PROFIT_AFTER_TAX", "item_value": 9999}]
            )
        if endpoint == "balance_sheet":
            return (
                statement("BS_TOTAL_ASSETS", [500, 520, 540, 560, 600])
                + statement("BS_EQUITY", [200, 210, 220, 230, 240])
                + statement("BS_SHORT_TERM_ASSETS", [150, 160, 170, 180, 200])
                + statement("BS_SHORT_TERM_LIABILITIES", [75, 80, 85, 90, 100])
                + statement("BS_TOTAL_LIABILITIES", [300, 310, 320, 330, 360])
            )
        if endpoint == "cash_flow":
            return statement("CF_NET_CASH_FLOWS_FROM_OPERATING_ACTIVITIES", [12, 13, 14, 15, 18])
        if endpoint == "order_book":
            return [{"bid_volume_1": 1000, "bid_volume_2": 800, "bid_volume_3": 600, "ask_volume_1": 200, "ask_volume_2": 200, "ask_volume_3": 200}]
        if endpoint == "proprietary_flow":
            return [{"time": f"2026-11-{day:02d}", "net_value": day * 2_000_000} for day in range(1, 21)]
        if endpoint == "insider_deal":
            return [{"transaction_date": "2026-11-20", "transaction_type": "buy"}]
        raise AssertionError(endpoint)


class SsiRawFeatureTests(unittest.TestCase):
    def test_bctc_formulas_and_pit_guard_are_ssi_owned(self):
        transport = FeatureTransport()
        income = transport.fetch("income_statement", "FHSC", "FPT", {})
        balance = transport.fetch("balance_sheet", "FHSC", "FPT", {})
        cash = transport.fetch("cash_flow", "FHSC", "FPT", {})
        result = features.fundamental_features(balance, income, cash, "2026-11-25", "Technology")
        self.assertAlmostEqual(result["ratio_roe"], 51 / 220)
        self.assertAlmostEqual(result["ratio_roa"], 51 / 550)
        self.assertAlmostEqual(result["ratio_gross_margin"], 0.4)
        self.assertAlmostEqual(result["ratio_net_margin"], 51 / 485)
        self.assertAlmostEqual(result["ratio_current"], 2.0)
        self.assertAlmostEqual(result["growth_revenue_yoy"], 0.25)
        self.assertAlmostEqual(result["growth_profit_yoy"], 0.5)
        self.assertAlmostEqual(result["cash_flow_quality"], 1.2)
        self.assertEqual(result["fundamental_period"], "2026-Q3")
        self.assertEqual(result["fundamental_formula_version"], features.FORMULA_VERSION)

    def test_active_session_fallback_supplies_depth_trade_size(self):
        result = features.flow_features(
            [], [], [],
            [{"bid_volume_1": 1000, "bid_volume_2": 800, "bid_volume_3": 600,
              "ask_volume_1": 200, "ask_volume_2": 200, "ask_volume_3": 200}],
            [],
            [{"active_buy_volume": 5000, "active_sell_volume": 5000,
              "buy_order_count": 50, "sell_order_count": 50}],
        )
        self.assertEqual(result["depth_trade_size_source"], "FHSC_ACTIVE_SESSION")
        self.assertAlmostEqual(result["depth_bid_multiple"], 24.0)
        self.assertAlmostEqual(result["depth_ask_multiple"], 6.0)

    def test_financial_sector_cashflow_quality_is_null(self):
        transport = FeatureTransport()
        result = features.fundamental_features(
            transport.fetch("balance_sheet", "FHSC", "FPT", {}),
            transport.fetch("income_statement", "FHSC", "FPT", {}),
            transport.fetch("cash_flow", "FHSC", "FPT", {}),
            "2026-11-25", "Ngân hàng",
        )
        self.assertIsNone(result["cash_flow_quality"])
        self.assertIsNotNone(result["cash_flow_operating"])

    def test_end_to_end_feature_rows_read_only_shared_raw(self):
        config = {
            "schema_version": 1, "namespace": "ssi-fhsc-raw", "sources": {},
            "market_history_calendar_days": 800, "flow_history_calendar_days": 45,
            "minimum_ohlcv_symbols": 1, "max_workers": 1, "universe": ["FPT"],
        }
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temp:
            root = Path(temp)
            manifest = raw.collect_release(
                config, FeatureTransport(), root, mode="full", signal_date=date(2026, 11, 25),
                created_at=datetime(2026, 11, 25, 4, 30, tzinfo=timezone.utc),
            )
            release = root / "releases" / manifest["release_id"]
            _, rows = features.build_feature_rows(release)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["input_layer"], "shared_raw")
            self.assertEqual(row["feature_engine"], "ssi")
            self.assertEqual(row["raw_release_id"], manifest["release_id"])
            self.assertEqual(row["snap_time"], "11:30")
            for key in ("willr_14", "bb_position", "price_vs_ema200_pct", "relative_return_20d", "position_52w", "adx", "supertrend", "ratio_roe", "growth_revenue_yoy", "foreign_net_5d", "depth_bid_multiple"):
                self.assertIsNotNone(row[key], key)

    def test_runtime_has_no_gen6_import_or_path(self):
        text = (ROOT / "scripts" / "ssi_raw_features.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("vnstock6", text)
        self.assertNotIn("output/serving", text)


if __name__ == "__main__":
    unittest.main()
