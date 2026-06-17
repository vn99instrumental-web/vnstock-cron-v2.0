"""
scripts/diag_ta_library.py — Verify vnstock_ta built-in indicators
====================================================================
MỤC ĐÍCH: Inventory chỉ số sẵn sàng trong `vnstock_ta` để quyết định
indicator nào DROP-IN dùng library, indicator nào KEEP custom (intraday).

Bối cảnh: vnstock_ta có 60 indicators trong 5 nhóm (trend/momentum/volatility
/volume/statistics). Pipeline hiện tại chỉ dùng 11. Trước khi code scoring
cho Tier 1 (linreg, donchian, ad, efi, willr), cần verify:
  1. Tên cột trả về exact (Series vs DataFrame)
  2. Shape so với OHLCV input
  3. Sample tail values để biết range/units
  4. VWAP: anchor="D" có phải session VWAP intraday hay daily rolling?

TRIGGER:
    workflow_dispatch → input script = scripts/diag_ta_library.py
Chạy bất cứ lúc nào — chỉ cần Quote.history() trả 3M data.

OUTPUT: log dạng table cho mỗi indicator + final decision matrix.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import logging
import traceback
import pandas as pd
import numpy as np

from vnstock_data import Quote
from vnstock_ta   import Indicator

from utils.helpers import now_ict, safe_run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# Mẫu thử: đa dạng sector + thanh khoản
TEST_SYMBOLS = ["HPG", "VCB", "FPT"]

# Indicators muốn verify, group theo tier roadmap
INDICATORS_TIER_1 = [
    # (category, name, callable_builder, scoring_use_case)
    ("trend",      "linreg",   lambda ta: ta.trend.linreg(length=20),
     "Slope angle objective; bổ sung EMA cross"),
    ("trend",      "aroon",    lambda ta: ta.trend.aroon(length=14),
     "Trend strength; ít noise hơn ADX khi sideways"),
    ("volatility", "donchian", lambda ta: ta.volatility.donchian(lower_length=20, upper_length=20),
     "20d high/low breakout — classic system"),
    ("volume",     "ad",       lambda ta: ta.volume.ad(),
     "A/D Line complement OBV"),
    ("volume",     "efi",      lambda ta: ta.volume.efi(length=13),
     "Force Index = volume × momentum"),
    ("momentum",   "willr",    lambda ta: ta.momentum.willr(length=14),
     "Williams %R — oversold/overbought alternative Stoch"),
]

INDICATORS_TIER_2 = [
    ("trend",      "psar",     lambda ta: ta.trend.psar(af0=0.02, af=0.02, max_af=0.2),
     "Trailing stop tự nhiên"),
    ("trend",      "ichimoku", lambda ta: ta.trend.ichimoku(tenkan=9, kijun=26, senkou=52),
     "Multi-component trend system"),
    ("volatility", "squeeze",  lambda ta: ta.volatility.squeeze(bb_length=20, bb_std=2.0, kc_length=20, kc_scalar=1.5),
     "BB+KC compression → breakout incoming"),
    ("momentum",   "cci",      lambda ta: ta.momentum.cci(length=20, c=0.015),
     "Mean reversion ±100"),
    ("volatility", "ui",       lambda ta: ta.volatility.ui(length=14),
     "Ulcer Index — drawdown-based risk"),
    ("statistics", "pivots",   lambda ta: ta.statistics.pivots(method="traditional"),
     "S/R levels — dùng cho step_price_levels"),
]

# VWAP — CAVEAT: cần test riêng để biết anchor behavior
INDICATORS_VWAP = [
    ("volume", "vwap_D", lambda ta: ta.volume.vwap(anchor="D"),
     "VWAP anchor=Daily — RỖNG hay rolling?"),
]

# Volume Profile — so sánh với manual implementation
INDICATORS_VP = [
    ("volume", "vp_w10", lambda ta: ta.volume.vp(width=10),
     "Volume Profile library — so với manual VP từ intraday"),
]


def _summarize_output(result, name: str) -> dict:
    """
    Trích metadata từ output của indicator: type, shape, columns, dtype,
    NaN count, sample tail.
    """
    info = {"name": name}
    if result is None:
        info["type"] = "None"
        return info

    info["type"] = type(result).__name__

    if isinstance(result, pd.Series):
        info["shape"]    = (len(result),)
        info["name_attr"] = result.name
        info["dtype"]    = str(result.dtype)
        info["nan_pct"]  = round(result.isna().sum() / max(len(result), 1) * 100, 1)
        try:
            tail = result.dropna().tail(3).round(4).to_dict()
        except Exception:
            tail = result.dropna().tail(3).to_dict()
        info["tail3"] = tail

    elif isinstance(result, pd.DataFrame):
        info["shape"]   = result.shape
        info["columns"] = list(result.columns)
        info["dtypes"]  = {c: str(result[c].dtype) for c in result.columns}
        info["nan_pct"] = {
            c: round(result[c].isna().sum() / max(len(result), 1) * 100, 1)
            for c in result.columns
        }
        try:
            tail = result.dropna(how="all").tail(3).round(4).to_dict(orient="list")
        except Exception:
            tail = result.tail(3).to_dict(orient="list")
        info["tail3_per_col"] = tail
    else:
        info["repr"] = repr(result)[:200]

    return info


def _format_info(info: dict) -> str:
    """Pretty-print 1 indicator result."""
    lines = []
    name = info.get("name", "?")
    typ  = info.get("type", "?")
    lines.append(f"   type     = {typ}")

    if typ == "Series":
        lines.append(f"   shape    = {info.get('shape')}")
        lines.append(f"   name     = {info.get('name_attr')}")
        lines.append(f"   dtype    = {info.get('dtype')}")
        lines.append(f"   nan%     = {info.get('nan_pct')}%")
        lines.append(f"   tail3    = {info.get('tail3')}")
    elif typ == "DataFrame":
        lines.append(f"   shape    = {info.get('shape')}")
        lines.append(f"   columns  = {info.get('columns')}")
        lines.append(f"   dtypes   = {info.get('dtypes')}")
        lines.append(f"   nan%     = {info.get('nan_pct')}")
        # Tail compact
        tail = info.get("tail3_per_col", {})
        for col, vals in tail.items():
            lines.append(f"   tail[{col}]= {vals}")
    elif typ == "None":
        lines.append(f"   → returned None")
    else:
        lines.append(f"   repr     = {info.get('repr')}")
    return "\n".join(lines)


def _run_indicator_batch(ta: Indicator, batch: list, batch_label: str,
                         results_accum: dict, symbol: str):
    """Test 1 batch indicators; append kết quả vào results_accum[symbol][name]."""
    log.info(f"\n──── {batch_label} ────")
    for cat, name, builder, use_case in batch:
        log.info(f"\n[{cat}.{name}]  use_case: {use_case}")
        try:
            result = builder(ta)
            info   = _summarize_output(result, name)
            print(_format_info(info))
            results_accum.setdefault(symbol, {})[name] = {
                "status": "OK",
                "type":   info.get("type"),
                "shape":  info.get("shape"),
                "columns": info.get("columns") if info.get("type") == "DataFrame" else None,
                "use_case": use_case,
            }
        except Exception as e:
            log.error(f"   ✗ ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
            results_accum.setdefault(symbol, {})[name] = {
                "status": "ERROR",
                "error":  f"{type(e).__name__}: {e}",
                "use_case": use_case,
            }


def _vwap_deep_test(ta: Indicator, df: pd.DataFrame, symbol: str):
    """
    VWAP deep test: phân biệt daily-rolling vs session-anchored.

    Test:
      1. Shape vs OHLCV → bằng nhau hay khác?
      2. So với manual VWAP (cumulative typical_price × volume / cumulative volume)
      3. Có reset mỗi phiên không?
    """
    log.info(f"\n──── VWAP DEEP TEST [{symbol}] ────")
    try:
        vwap_d = ta.volume.vwap(anchor="D")
        info   = _summarize_output(vwap_d, "vwap_D")
        print(_format_info(info))

        if isinstance(vwap_d, pd.Series):
            n_in  = len(df)
            n_out = len(vwap_d)
            log.info(f"   OHLCV rows = {n_in}, VWAP rows = {n_out}")
            if n_in == n_out:
                log.info("   → Output match input length ⇒ per-bar VWAP value (KHÔNG phải session aggregate).")
            else:
                log.info(f"   → Output length KHÁC input ⇒ có thể đã resample/aggregate.")

            # Compare với manual cumulative VWAP từ daily OHLCV
            try:
                tp        = (df["high"] + df["low"] + df["close"]) / 3
                cum_pv    = (tp * df["volume"]).cumsum()
                cum_v     = df["volume"].cumsum()
                vwap_man  = cum_pv / cum_v

                tail_lib = vwap_d.dropna().tail(3).round(2).tolist()
                tail_man = vwap_man.dropna().tail(3).round(2).tolist()
                log.info(f"   Library  tail3 = {tail_lib}")
                log.info(f"   Manual cum VWAP tail3 = {tail_man}")
                if tail_lib and tail_man:
                    diff_pct = abs(tail_lib[-1] - tail_man[-1]) / tail_man[-1] * 100
                    log.info(f"   Diff cuối = {diff_pct:.2f}%")
                    if diff_pct < 0.5:
                        log.info("   → Library VWAP ≈ Manual cumulative VWAP từ ngày đầu data.")
                        log.info("   → VERDICT: VWAP là CUMULATIVE từ start of df (không reset per session).")
                    else:
                        log.info("   → Library VWAP KHÁC manual cumulative đáng kể.")
                        log.info("   → VERDICT: Có thể là rolling VWAP per bar / anchor period riêng.")
            except Exception as e:
                log.warning(f"   Manual VWAP compare failed: {e}")

    except Exception as e:
        log.error(f"   ✗ VWAP fetch failed: {type(e).__name__}: {e}")


def _vp_deep_test(ta: Indicator, df: pd.DataFrame, symbol: str):
    """
    Volume Profile deep test: so output library với manual VP từ daily bars.
    """
    log.info(f"\n──── VOLUME PROFILE DEEP TEST [{symbol}] ────")
    try:
        vp_lib = ta.volume.vp(width=10)
        info   = _summarize_output(vp_lib, "vp_w10")
        print(_format_info(info))

        # Nếu là DataFrame → in hết rows (chỉ 10 rows do width=10)
        if isinstance(vp_lib, pd.DataFrame) and len(vp_lib) <= 30:
            log.info("   FULL output:")
            for _, row in vp_lib.iterrows():
                log.info(f"     {row.to_dict()}")

        log.info("   So với current manual VP (build_volume_profile từ intraday tick):")
        log.info("     - Library VP: input là OHLCV BARS daily → price bucket vol từ daily")
        log.info("     - Manual  VP: input là intraday TICK → bucket vol per tick")
        log.info("   ⇒ Library VP có granularity THẤP hơn manual, nhưng có thể dùng cho")
        log.info("     daily VP score (level S/R dài hạn). KHÔNG thay thế intraday VP.")
    except Exception as e:
        log.error(f"   ✗ VP fetch failed: {type(e).__name__}: {e}")


def _final_decision_matrix(results: dict):
    """In bảng quyết định cuối: indicator nào ADOPT vs SKIP."""
    log.info("\n")
    log.info("═" * 72)
    log.info("FINAL DECISION MATRIX — indicator nào nên adopt vào scoring v2")
    log.info("═" * 72)

    # Aggregate qua các symbol: nếu ≥2/3 mã pass → OK
    all_names = set()
    for sym_results in results.values():
        all_names.update(sym_results.keys())

    log.info(f"\n{'Indicator':<14} {'Pass/Total':<12} {'Type':<12} {'Columns/Note':<35}")
    log.info("─" * 75)

    decisions = []
    for name in sorted(all_names):
        ok_count = 0
        types    = set()
        cols     = None
        use_case = ""
        for sym, sym_results in results.items():
            info = sym_results.get(name, {})
            if info.get("status") == "OK":
                ok_count += 1
                types.add(info.get("type", ""))
                if info.get("columns"):
                    cols = info["columns"]
                use_case = info.get("use_case", "")

        n_sym  = len(results)
        t_str  = "|".join(sorted(types)) if types else "—"
        c_str  = (",".join(cols)[:32] + "…") if cols and len(",".join(cols)) > 32 \
                 else (",".join(cols) if cols else "(Series)")

        log.info(f"{name:<14} {ok_count}/{n_sym:<10} {t_str:<12} {c_str:<35}")

        if ok_count == n_sym:
            verdict = "✅ ADOPT"
        elif ok_count >= max(1, n_sym // 2):
            verdict = "⚠️  Partial — adopt with guard"
        else:
            verdict = "❌ SKIP — library broken"
        decisions.append((name, verdict, use_case))

    log.info("\n──── Recommendation per indicator ────")
    for name, verdict, use_case in decisions:
        log.info(f"  {verdict:<32} {name:<12} — {use_case}")


def run():
    log.info(f"=== TA LIBRARY DIAGNOSTIC ({now_ict():%Y-%m-%d %H:%M:%S} ICT) ===")
    log.info(f"Test symbols: {TEST_SYMBOLS}")
    log.info(f"Indicators to test: Tier1={len(INDICATORS_TIER_1)} + "
             f"Tier2={len(INDICATORS_TIER_2)} + VWAP + VP")

    results = {}  # {symbol: {name: {status, type, shape, columns, ...}}}

    for sym in TEST_SYMBOLS:
        log.info("\n")
        log.info("╔" + "═" * 70 + "╗")
        log.info(f"║  SYMBOL: {sym:<60}║")
        log.info("╚" + "═" * 70 + "╝")

        df = safe_run(f"history {sym}",
            lambda s=sym: Quote(source="VCI", symbol=s).history(length="3M", interval="1D"))

        if df is None or df.empty:
            log.error(f"   [{sym}] history empty — skip")
            continue

        # Ensure required columns
        required = ["open", "high", "low", "close", "volume"]
        missing  = [c for c in required if c not in df.columns]
        if missing:
            log.error(f"   [{sym}] missing OHLCV cols: {missing} (have: {list(df.columns)})")
            continue

        log.info(f"   OHLCV ready: {df.shape}, date range {df['time'].iloc[0] if 'time' in df.columns else '?'} → "
                 f"{df['time'].iloc[-1] if 'time' in df.columns else '?'}")

        try:
            ta = Indicator(data=df)
        except Exception as e:
            log.error(f"   Indicator init failed: {e}")
            continue

        # Tier 1
        _run_indicator_batch(ta, INDICATORS_TIER_1, "TIER 1 INDICATORS", results, sym)
        # Tier 2
        _run_indicator_batch(ta, INDICATORS_TIER_2, "TIER 2 INDICATORS", results, sym)
        # VWAP deep
        _vwap_deep_test(ta, df, sym)
        # VP deep
        _vp_deep_test(ta, df, sym)

    # Final aggregated decision
    _final_decision_matrix(results)

    log.info("\n=== DONE ===")
    log.info("Reference: copy log output above → quyết định indicator nào adopt.")
    log.info("Sau khi adopt: bump SCORING_VERSION trong step_scoring_v2.py để tách performance ledger.")


if __name__ == "__main__":
    run()
