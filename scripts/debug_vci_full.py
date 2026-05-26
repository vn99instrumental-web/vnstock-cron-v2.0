"""
debug_vci_full.py — Comprehensive VCI data source diagnostic
==============================================================
Test toàn bộ các method VCI mà project đang dùng (hoặc có thể dùng):
  - Quote(VCI): history, intraday, price_depth, quote
  - Listing(VCI): symbols_by_exchange, symbols_by_industries, all_symbols
  - Trading(VCI): foreign_trade, prop_trade, insider_deal
  - Finance(VCI): ratio, income_statement, balance_sheet, cash_flow
  - Reference: industry list

Mục đích:
  1. Confirm signatures + params hiện tại
  2. Dump DataFrame structure (columns, dtypes, shape)
  3. Test khả năng work với HPG (industrial) + VCB (bank) + VND (securities)
  4. Identify methods broken (như prop_trade trước đây)
"""
import os
import sys
import traceback

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import pandas as pd

try:
    import vnstock_data
    print(f"vnstock_data version: "
          f"{getattr(vnstock_data, '__version__', 'unknown')}")
except Exception as e:
    print(f"vnstock_data import failed: {e}")

pd.set_option("display.max_rows", 30)
pd.set_option("display.max_columns", 25)
pd.set_option("display.width", 220)
pd.set_option("display.max_colwidth", 50)


TEST_SYMBOLS = ["HPG", "VCB", "VND"]   # industrial, bank, securities


def section(title: str):
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")


def dump_df(df, label: str, max_show: int = 5):
    """Dump DataFrame info: shape, cols, dtypes, sample"""
    if df is None:
        print(f"    {label}: None")
        return
    if not isinstance(df, pd.DataFrame):
        print(f"    {label}: not DataFrame ({type(df).__name__})")
        try:
            print(f"      repr: {df!r}"[:200])
        except Exception:
            pass
        return
    if df.empty:
        print(f"    {label}: empty DataFrame")
        return

    print(f"    {label}: shape={df.shape}, cols={df.columns.tolist()[:10]}"
          f"{'...' if len(df.columns) > 10 else ''}")
    # Series.items() returns iterator — can't slice, use list() first
    dtypes_list = list(df.dtypes.items())[:5]
    dtypes_str = ", ".join(f"{c}:{str(d)[:8]}" for c, d in dtypes_list)
    print(f"      dtypes (first 5): {dtypes_str}")
    print(f"      sample (head 3):")
    try:
        # Print first 3 rows with limited cols
        cols_to_show = df.columns.tolist()[:8]
        sample = df[cols_to_show].head(3).to_string()
        for line in sample.split('\n'):
            print(f"        {line}")
    except Exception as e:
        print(f"      sample error: {e}")


def safe_test(label: str, fn):
    """Run fn, catch exceptions, print result."""
    try:
        result = fn()
        return result
    except TypeError as e:
        # Often signature issue — useful info
        print(f"    ❌ {label}: TypeError (likely bad signature)")
        print(f"      {e}")
        return None
    except AttributeError as e:
        # Method doesn't exist
        print(f"    ❌ {label}: AttributeError (method missing)")
        print(f"      {e}")
        return None
    except ValueError as e:
        print(f"    ❌ {label}: ValueError")
        print(f"      {e}")
        return None
    except Exception as e:
        print(f"    ❌ {label}: {type(e).__name__}: {e}")
        return None


# =====================================================
# 1. Quote — already used heavily
# =====================================================

def test_quote(symbol: str):
    section(f"Quote(VCI, {symbol})")
    from vnstock_data import Quote

    q = Quote(source="VCI", symbol=symbol)

    # 1.1 history — used in step_snapshot
    print("\n  • history(length='4M', interval='1D'):")
    df = safe_test("history",
        lambda: q.history(length="4M", interval="1D"))
    dump_df(df, "result")

    # 1.2 history with start/end
    print("\n  • history(start='2026-01-01', end='2026-05-01', interval='1D'):")
    df = safe_test("history_dates",
        lambda: q.history(start="2026-01-01", end="2026-05-01", interval="1D"))
    dump_df(df, "result")

    # 1.3 intraday
    print("\n  • intraday(page_size=100):")
    df = safe_test("intraday",
        lambda: q.intraday(page_size=100))
    dump_df(df, "result")

    # 1.4 price_depth — used in step_snapshot
    print("\n  • price_depth():")
    df = safe_test("price_depth",
        lambda: q.price_depth())
    dump_df(df, "result")

    # 1.5 Try Quote() = today price snapshot if exists
    print("\n  • Try other Quote methods:")
    for method in ["quote", "last_price", "snapshot", "ticker_info"]:
        if hasattr(q, method):
            print(f"    {method}: available — testing")
            df = safe_test(method, lambda m=method: getattr(q, m)())
            dump_df(df, f"  {method}")


# =====================================================
# 2. Listing — used in step3_context
# =====================================================

def test_listing():
    section("Listing(VCI)")
    from vnstock_data import Listing

    l = Listing(source="VCI")

    # 2.1 symbols_by_exchange — used in step3
    print("\n  • symbols_by_exchange(exchange='HSX'):")
    df = safe_test("by_exchange_HSX",
        lambda: l.symbols_by_exchange(exchange="HSX"))
    dump_df(df, "result")

    # 2.2 No-arg version
    print("\n  • symbols_by_exchange() [no arg]:")
    df = safe_test("by_exchange_all",
        lambda: l.symbols_by_exchange())
    dump_df(df, "result")

    # 2.3 symbols_by_industries — may help news matching
    print("\n  • symbols_by_industries():")
    df = safe_test("by_industries",
        lambda: l.symbols_by_industries())
    dump_df(df, "result")

    # 2.4 all_symbols
    print("\n  • all_symbols():")
    df = safe_test("all_symbols",
        lambda: l.all_symbols() if hasattr(l, "all_symbols") else None)
    dump_df(df, "result")

    # 2.5 Indices / ETFs / Futures
    for method in ["indices", "etfs", "futures", "covered_warrants",
                   "symbols_by_group", "fund_listing"]:
        if hasattr(l, method):
            print(f"\n  • {method}():")
            df = safe_test(method, lambda m=method: getattr(l, m)())
            dump_df(df, f"  result")


# =====================================================
# 3. Trading — used in step_snapshot for FF
# =====================================================

def test_trading(symbol: str):
    section(f"Trading(VCI, {symbol})")
    from vnstock_data import Trading

    t = Trading(source="VCI", symbol=symbol)

    # 3.1 foreign_trade — currently use CafeF due to VCI ConnectionError
    print("\n  • foreign_trade(start='2026-05-01', end='2026-05-26'):")
    df = safe_test("foreign_trade",
        lambda: t.foreign_trade(start="2026-05-01", end="2026-05-26"))
    dump_df(df, "result")

    # 3.2 prop_trade — bug AttributeError trước đây
    print("\n  • prop_trade(start='2026-05-01', end='2026-05-26'):")
    df = safe_test("prop_trade",
        lambda: t.prop_trade(start="2026-05-01", end="2026-05-26"))
    dump_df(df, "result")

    # 3.3 insider_deal
    print("\n  • insider_deal(limit=5):")
    df = safe_test("insider_deal",
        lambda: t.insider_deal(limit=5))
    dump_df(df, "result")

    # 3.4 Try other methods
    for method in ["price_board", "trading_history", "block_deals"]:
        if hasattr(t, method):
            print(f"\n  • {method}():")
            df = safe_test(method, lambda m=method: getattr(t, m)())
            dump_df(df, f"  result")


# =====================================================
# 4. Finance(VCI) — alternative to KBS
# =====================================================

def test_finance(symbol: str):
    section(f"Finance(VCI, {symbol})")
    from vnstock_data import Finance

    f = Finance(source="VCI", symbol=symbol)

    # 4.1 ratio
    print("\n  • ratio(period='quarter', limit=1):")
    df = safe_test("ratio_q",
        lambda: f.ratio(period="quarter", limit=1))
    dump_df(df, "result")

    print("\n  • ratio(period='year', limit=1):")
    df = safe_test("ratio_y",
        lambda: f.ratio(period="year", limit=1))
    dump_df(df, "result")

    # 4.2 income_statement
    print("\n  • income_statement(period='quarter', limit=4):")
    df = safe_test("is_q",
        lambda: f.income_statement(period="quarter", limit=4))
    dump_df(df, "result")

    # 4.3 balance_sheet
    print("\n  • balance_sheet(period='quarter', limit=1):")
    df = safe_test("bs_q",
        lambda: f.balance_sheet(period="quarter", limit=1))
    dump_df(df, "result")

    # 4.4 cash_flow
    print("\n  • cash_flow(period='quarter', limit=1):")
    df = safe_test("cf_q",
        lambda: f.cash_flow(period="quarter", limit=1))
    dump_df(df, "result")

    print("\n  • cash_flow(period='year', limit=1):")
    df = safe_test("cf_y",
        lambda: f.cash_flow(period="year", limit=1))
    dump_df(df, "result")


# =====================================================
# 5. Reference — industry list
# =====================================================

def test_reference():
    section("Reference()")
    from vnstock_data import Reference

    r = Reference()

    # 5.1 industry
    print("\n  • industry.list():")
    df = safe_test("industry_list",
        lambda: r.industry.list() if hasattr(r, "industry") else None)
    dump_df(df, "result")

    # 5.2 Try other reference data
    for method_path in [
        ("symbols", "symbols.list"),
        ("exchanges", "exchanges.list"),
        ("icb", "icb.list"),
    ]:
        attr_name, label = method_path
        if hasattr(r, attr_name):
            sub = getattr(r, attr_name)
            if hasattr(sub, "list"):
                print(f"\n  • {label}():")
                df = safe_test(label, lambda s=sub: s.list())
                dump_df(df, "result")


# =====================================================
# 6. Analytics — used in step3_context
# =====================================================

def test_analytics():
    section("Analytics()")
    from vnstock_data import Analytics

    a = Analytics()

    # 6.1 valuation(VNINDEX).evaluation
    print("\n  • valuation('VNINDEX').evaluation(duration='5Y'):")
    df = safe_test("valuation_eval",
        lambda: a.valuation("VNINDEX").evaluation(duration="5Y"))
    dump_df(df, "result")

    # 6.2 Try valuation on a single stock
    print("\n  • valuation('HPG').evaluation(duration='1Y'):")
    df = safe_test("valuation_HPG",
        lambda: a.valuation("HPG").evaluation(duration="1Y"))
    dump_df(df, "result")


# =====================================================
# 7. TopStock — used in step_snapshot ranking
# =====================================================

def test_topstock():
    section("TopStock()")
    from vnstock_data import TopStock

    t = TopStock()

    # 7.1 gainer/loser (currently use VND source)
    print("\n  • gainer(index='VNINDEX', limit=5):")
    df = safe_test("gainer",
        lambda: t.gainer(index="VNINDEX", limit=5))
    dump_df(df, "result")

    print("\n  • loser(index='VNINDEX', limit=5):")
    df = safe_test("loser",
        lambda: t.loser(index="VNINDEX", limit=5))
    dump_df(df, "result")

    # 7.2 Try other top methods
    for method in ["liquid", "volume", "value", "by_market_cap"]:
        if hasattr(t, method):
            print(f"\n  • {method}(index='VNINDEX', limit=5):")
            df = safe_test(method,
                lambda m=method: getattr(t, m)(index="VNINDEX", limit=5))
            dump_df(df, "  result")


# =====================================================
# MAIN
# =====================================================

def main():
    print("=" * 80)
    print("  VCI Source Diagnostic — All methods used by project")
    print("=" * 80)

    # Section 1: Quote (3 symbols)
    for sym in TEST_SYMBOLS:
        test_quote(sym)

    # Section 2: Listing
    test_listing()

    # Section 3: Trading (1 symbol enough — same schema)
    test_trading("HPG")

    # Section 4: Finance VCI (3 symbols — schema may differ by sector)
    for sym in TEST_SYMBOLS:
        test_finance(sym)

    # Section 5: Reference
    test_reference()

    # Section 6: Analytics
    test_analytics()

    # Section 7: TopStock
    test_topstock()

    print("\n" + "=" * 80)
    print("  DONE — Review output để identify:")
    print("    1. Methods broken (TypeError/AttributeError)")
    print("    2. New methods chưa dùng (có thể tận dụng)")
    print("    3. Param signatures hiện tại")
    print("    4. DataFrame structure mismatch sector-wise")
    print("=" * 80)


if __name__ == "__main__":
    main()
