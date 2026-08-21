#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
backtest_v2v4.py  —  Backtest re-score V2.3 & V4 trên N ngày lịch sử (Cách A)
================================================================================
Ý tưởng: KHÔNG viết lại math của model. Thay vào đó:
  1. Fetch 1 lần chuỗi nến NGÀY (OHLCV) cho từng mã + VNINDEX (đủ dài để warmup TA).
  2. Với mỗi ngày quá khứ t (đi TUẦN TỰ từ cũ → mới):
       - CHẶN tầng fetch giá của repo (monkeypatch `Quote`) để mọi hàm feature
         (get_snapshot / get_ta) chỉ "thấy" nến ≤ t  → feature as-of ngày t.
       - Gọi THẲNG build_one() của repo để dựng row (TA thật, không tái hiện).
       - Gọi THẲNG score_symbol_v2() và score_symbol_v4() của repo → quyết định.
       - Tính forward return t→t+h từ chính chuỗi nến.
  3. Tổng hợp hiệu năng rổ BUY: hit-rate, TB, excess vs thị trường, trừ phí.

────────────────────────────────────────────────────────────────────────────
GIỚI HẠN TRUNG THỰC (đọc kỹ — đây là điều KHÔNG né được):
  • order-flow (of_bp, _of_buy/sell_count, depth_wall...) và FF INTRADAY là dữ
    liệu tick/real-time → KHÔNG tái tạo được cho ngày quá khứ. Script TRUNG HOÀ
    chúng (đặt về mức trung tính) và gắn cờ. ⇒ đây là backtest "model TRỪ flow/FF
    intraday". flow có weight 0.27 trong khung TRADE V4 → kết quả là XẤP XỈ.
  • fundamental: ratio_summary() trả số HIỆN TẠI (không point-in-time) → có
    look-ahead nhẹ trong quý. Script dùng fin_cache hiện có; ai cần chuẩn hơn
    phải nạp báo cáo theo quý đúng thời điểm.
  • regime: script suy regime từ BREADTH của rổ (repo _compute_breadth +
    classify_regime_breadth) và đặt index_raw = breadth_raw (bỏ nửa index cap-
    weighted). hysteresis được REPLAY tuần tự đúng cơ chế repo.
  • các sub-score V2.3 phụ thuộc context (RS vs VNINDEX, market breadth) chỉ được
    cấp context tối thiểu → có thể xấp xỉ.
Tất cả cờ trên được in ở đầu report + ghi cột `_fidelity_*` trong CSV.
────────────────────────────────────────────────────────────────────────────
CÁCH CHẠY (trong môi trường CÓ vnstock_data, vd GitHub Actions debug.yml / local):
    python scripts/backtest_v2v4.py --days 100 --fetch-length 16M
Kết quả: in bảng ra log + ghi output/backtest_v2v4_report.csv (chi tiết từng lệnh)
         và output/backtest_v2v4_summary.csv (bảng tổng hợp).
================================================================================
"""
import os
import sys
import argparse
import logging
import traceback
from datetime import datetime, timedelta
from collections import defaultdict, Counter

os.environ.setdefault("VNSTOCK_INTERACTIVE", "0")
os.environ.setdefault("VNSTOCK_LANGUAGE", "en")
# tắt prefetch/kill-switch phụ để không nhiễu backtest
os.environ.setdefault("PREFETCH_ENABLED", "0")

# repo root vào sys.path (script nằm ở scripts/)
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backtest_v2v4")

# ── import code THẬT của repo (không copy math) ──────────────────────────────
import steps.v2f_step_snapshot as SNAP
from steps.v2f_step_scoring import score_symbol_v2
from steps.v2f_step_scoring_v4 import (
    score_symbol_v4, _compute_breadth, _apply_hysteresis,
    factor_caps, active_signals, _augment_caps, validate_registry,
    FACTORS, gate_for,
)
from utils.regime_v42 import classify_regime_breadth, more_bearish
try:
    from steps.v2f_step_scoring_v4 import MIN_BREADTH_N
except Exception:
    MIN_BREADTH_N = 30

# universe + industry map
try:
    from utils.v2f_universe import get_universe  # kỳ vọng trả list (symbol, group) hoặc dict
except Exception:
    get_universe = None

from config import OUTPUT_DIR  # noqa

ROUND_TRIP_COST = 0.40  # % — phí khứ hồi giữa (0.30–0.50)
HORIZONS = [("ret_1d", 1), ("ret_3d", 3), ("ret_5d", 5), ("ret_10d", 10)]

# ══════════════════════════════════════════════════════════════════════════
# 1. FETCH DỮ LIỆU 1 LẦN (dùng Quote THẬT của repo, source VCI)
# ══════════════════════════════════════════════════════════════════════════
BARS = {}          # symbol -> DataFrame[time, open, high, low, close, volume]  (time = date)
_REAL_QUOTE = SNAP.Quote


def _norm_hist(df):
    import pandas as pd
    if df is None or getattr(df, "empty", True):
        return None
    df = df.copy()
    # chuẩn hoá cột time về datetime.date để so sánh as-of
    tcol = "time" if "time" in df.columns else ("date" if "date" in df.columns else None)
    if tcol is None:
        return None
    df["time"] = pd.to_datetime(df[tcol]).dt.normalize()
    keep = [c for c in ["time", "open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].sort_values("time").reset_index(drop=True)


def fetch_all_bars(symbols, fetch_length):
    """Fetch nến ngày cho từng mã + VNINDEX, 1 lần. Dùng Quote THẬT (có network)."""
    import time as _t
    allsyms = list(symbols) + ["VNINDEX"]
    for i, sym in enumerate(allsyms):
        try:
            df = _REAL_QUOTE(source="VCI", symbol=sym).history(length=fetch_length, interval="1D")
            nd = _norm_hist(df)
            if nd is not None and len(nd) >= 30:
                BARS[sym] = nd
                log.info("  [%d/%d] %s: %d nến (%s → %s)",
                         i + 1, len(allsyms), sym, len(nd),
                         nd['time'].iloc[0].date(), nd['time'].iloc[-1].date())
            else:
                log.warning("  %s: không đủ nến (bỏ)", sym)
        except Exception as e:
            log.warning("  %s: fetch lỗi %s", sym, e)
        _t.sleep(0.30)  # tôn trọng VCI Silver ~300 req/min


# ══════════════════════════════════════════════════════════════════════════
# 2. SHIM AS-OF: chặn Quote để feature chỉ thấy nến ≤ AS_OF
# ══════════════════════════════════════════════════════════════════════════
_AS_OF = None  # datetime.date — set mỗi ngày backtest


def _length_to_bars(length):
    if not length:
        return None
    length = str(length).upper()
    if length.endswith("Y"):
        return int(float(length[:-1]) * 252)
    if length.endswith("M"):
        return int(float(length[:-1]) * 21)
    if length.endswith("D"):
        return int(length[:-1])
    try:
        return int(length)
    except Exception:
        return None


class _AsOfQuote:
    """Thay Quote thật: .history() trả nến của symbol cắt ≤ _AS_OF."""
    def __init__(self, source=None, symbol=None, **kw):
        self.symbol = symbol

    def history(self, length=None, interval="1D", **kw):
        import pandas as pd
        df = BARS.get(self.symbol)
        if df is None:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        cut = df[df["time"] <= pd.Timestamp(_AS_OF)]
        n = _length_to_bars(length)
        return (cut.tail(n).reset_index(drop=True) if n else cut.reset_index(drop=True))


def _neutral_flow(symbol, *a, **kw):
    """Trung hoà order-flow/FF (không tái tạo được cho quá khứ). Gắn cờ."""
    return {
        "symbol": symbol,
        # order-flow đặt trung tính:
        "_of_buy_count": 0, "_of_sell_count": 0, "_of_total_trades": 0,
        "_of_avg_size": None, "_of_distribution": None,
        "of_bp": None, "order_flow_score": 0,
        # FF trung tính:
        "ff_net_val_5d": 0, "ff_intra_flag_pts": 0, "ff_room": None,
        "_backtest_flow_neutralized": True,
    }


# ══════════════════════════════════════════════════════════════════════════
# 3. CTX / REGIME cho từng ngày (tái dùng repo helpers)
# ══════════════════════════════════════════════════════════════════════════
def build_ctx_and_regime(rows, as_of, index_regime_override=None):
    """
    Trả (ctx, regime_hiệu_lực, raw_regime, divergence).
    - breadth_raw: từ repo _compute_breadth + classify_regime_breadth (đúng như V4 run).
    - index_raw : không tái tạo được nội bộ context step → mặc định = breadth_raw
                  (more_bearish thành no-op). Có thể override nếu bạn tự tính.
    - hysteresis: replay tuần tự (state persist qua OUTPUT_DIR như repo).
    """
    ctx = {"_snap_time": as_of.strftime("%Y-%m-%d 15:00"), "_backtest": True}
    brd = _compute_breadth(rows)
    if brd.get("n", 0) >= MIN_BREADTH_N:
        breadth_raw = classify_regime_breadth(
            brd["share_50"], brd["share_200"], brd["med_c5"], brd["med_c20"]
        )["regime_raw"]
    else:
        breadth_raw = "UNKNOWN"
    index_raw = index_regime_override or breadth_raw
    raw_regime = more_bearish(index_raw, breadth_raw)
    regime, _hyst = _apply_hysteresis(raw_regime, as_of.strftime("%Y-%m-%d"))
    div = breadth_raw not in (index_raw, "UNKNOWN")
    # cấp regime xuống row để scorer nào đọc _regime/_ctx_regime vẫn đúng
    for r in rows:
        r["_regime"] = regime
        r["_ctx_regime"] = regime
    return ctx, regime, raw_regime, div, brd


# ══════════════════════════════════════════════════════════════════════════
# 4. VÒNG BACKTEST
# ══════════════════════════════════════════════════════════════════════════
def load_universe():
    """Trả list (symbol, group). Fallback: lấy từ ledger nếu util không có."""
    if get_universe:
        u = get_universe()
        out = []
        for item in u:
            if isinstance(item, (list, tuple)):
                out.append((item[0], item[1] if len(item) > 1 else "VN100"))
            elif isinstance(item, dict):
                out.append((item.get("symbol"), item.get("group", "VN100")))
            elif isinstance(item, str):
                out.append((item, "VN100"))
        return [(s, g) for s, g in out if s]
    # fallback: đọc universe từ ledger predictions gần nhất
    import glob, json
    syms = set()
    for f in sorted(glob.glob(os.path.join(OUTPUT_DIR, "history/v2f_predictions/2026-*.jsonl")))[-1:]:
        for line in open(f):
            try:
                syms.add(json.loads(line)["symbol"])
            except Exception:
                pass
    return [(s, "VN100") for s in sorted(syms)]


def load_industry_map():
    import glob, json
    for cand in ["industry_map.json", "cache/industry_map.json", "v2f_universe.json"]:
        p = os.path.join(OUTPUT_DIR, cand)
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if isinstance(d, list):
                    return d
                if isinstance(d, dict) and isinstance(d.get("rows"), list):
                    return d["rows"]
            except Exception:
                pass
    log.warning("Không thấy industry_map → dùng rỗng (một số sub-score ngành sẽ trung tính)")
    return []


def load_fin_cache():
    import glob, json
    for cand in ["cache/finance_cache.json", "finance_cache.json",
                 "cache/finance_scan.json", "v2f_finance.json"]:
        p = os.path.join(OUTPUT_DIR, cand)
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                log.info("fin_cache: dùng %s", cand)
                return d if isinstance(d, dict) else {}
            except Exception:
                pass
    log.warning("Không thấy finance_cache → fundamental sẽ thiếu (data-gate của V4 tự co ngưỡng)")
    return {}


def trading_dates_from_vnindex(days):
    """Lấy N ngày giao dịch gần nhất CÓ ĐỦ forward (chừa 10 nến tương lai cho ret_10d)."""
    idx = BARS.get("VNINDEX")
    if idx is None or idx.empty:
        raise SystemExit("Thiếu nến VNINDEX — không xác định được lịch giao dịch.")
    all_dates = list(idx["time"])
    usable = all_dates[:-10] if len(all_dates) > 10 else []  # chừa forward tối đa
    return [d.date() for d in usable[-days:]]


def fwd_returns(symbol, as_of):
    """Trả dict ret_1d/3d/5d/10d (%) từ nến của symbol; None nếu chưa đủ future bar."""
    import pandas as pd
    df = BARS.get(symbol)
    if df is None:
        return {}
    ts = df[df["time"] <= pd.Timestamp(as_of)]
    if ts.empty:
        return {}
    i = len(ts) - 1
    c0 = float(df["close"].iloc[i])
    out = {}
    for name, h in HORIZONS:
        j = i + h
        if j < len(df) and c0:
            out[name] = (float(df["close"].iloc[j]) / c0 - 1.0) * 100.0
        else:
            out[name] = None
    return out


def run_backtest(days, fetch_length):
    validate_registry()
    caps = _augment_caps({hz: factor_caps(hz) for hz in ("trade", "hold")})
    actives = {hz: active_signals(hz) for hz in ("trade", "hold")}

    universe = load_universe()
    symbols = [s for s, _ in universe]
    group_of = {s: g for s, g in universe}
    log.info("Universe: %d mã", len(symbols))

    log.info("=== FETCH nến (%s) — 1 lần ===", fetch_length)
    fetch_all_bars(symbols, fetch_length)
    if "VNINDEX" not in BARS:
        raise SystemExit("Không fetch được VNINDEX.")

    industry_map = load_industry_map()
    fin_cache = load_fin_cache()

    # reset state hysteresis để replay sạch từ đầu
    st = os.path.join(OUTPUT_DIR, "v2f_v4_regime_state.json")
    if os.path.exists(st):
        os.remove(st)

    dates = trading_dates_from_vnindex(days)
    log.info("=== BACKTEST %d ngày: %s → %s ===", len(dates), dates[0], dates[-1])

    records = []  # mỗi dòng = 1 (mã, ngày) với decision v2/v4 + forward return

    global _AS_OF
    # bật shim: feature chỉ thấy nến ≤ as-of; flow/FF trung hoà
    SNAP.Quote = _AsOfQuote
    _real_get_flow = SNAP.get_flow
    SNAP.get_flow = _neutral_flow
    try:
        for di, d in enumerate(dates):
            _AS_OF = d
            rows = []
            for sym in symbols:
                if sym not in BARS:
                    continue
                try:
                    r = SNAP.build_one(sym, group_of.get(sym, "VN100"),
                                       market_open=False,
                                       industry_map=industry_map, fin_cache=fin_cache)
                    if r and not r.get("error") and r.get("price") is not None:
                        rows.append(r)
                except Exception:
                    log.debug("build_one %s @%s lỗi:\n%s", sym, d, traceback.format_exc())
            if len(rows) < MIN_BREADTH_N:
                log.warning("  %s: chỉ %d mã có feature — bỏ ngày này", d, len(rows))
                continue

            ctx, regime, raw_regime, div, brd = build_ctx_and_regime(rows, d)

            for r in rows:
                sym = r["symbol"]
                # ── V2.3 (context tối thiểu, news/order_flow rỗng) ──
                try:
                    v2 = score_symbol_v2(r, ctx, {}, {})
                    dec_v2 = v2.get("decision")
                    sc_v2 = v2.get("total_score")
                except Exception:
                    dec_v2, sc_v2 = None, None
                # ── V4 (đúng cách run() gọi) ──
                try:
                    v4 = score_symbol_v4(dict(r), ctx, caps, actives,
                                         regime, raw_regime,
                                         ctx.get("market_regime_v42", "UNKNOWN"),
                                         regime_divergence=div)
                    dec_v4 = v4.get("decision")
                    sc_v4 = v4.get("score_trade")
                except Exception:
                    log.debug("v4 %s @%s lỗi:\n%s", sym, d, traceback.format_exc())
                    dec_v4, sc_v4 = None, None

                rec = {
                    "signal_date": d.isoformat(), "symbol": sym, "regime": regime,
                    "dec_v2": dec_v2, "score_v2": sc_v2,
                    "dec_v4": dec_v4, "score_v4": sc_v4,
                    "_fidelity_flow_neutralized": True,
                    "_fidelity_regime": "breadth_only",
                }
                rec.update(fwd_returns(sym, d))
                records.append(rec)

            _today_recs = [x for x in records if x["signal_date"] == d.isoformat()]
            _b2 = sum(1 for x in _today_recs if x["dec_v2"] in ("BUY", "STRONG BUY"))
            _b4 = sum(1 for x in _today_recs if x["dec_v4"] in ("BUY", "STRONG BUY"))
            log.info("  [%d/%d] %s regime=%s | mã=%d | BUY v2=%d v4=%d",
                     di + 1, len(dates), d, regime, len(rows), _b2, _b4)
    finally:
        SNAP.Quote = _REAL_QUOTE
        SNAP.get_flow = _real_get_flow

    return records


# ══════════════════════════════════════════════════════════════════════════
# 5. TỔNG HỢP & REPORT
# ══════════════════════════════════════════════════════════════════════════
def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _hit(xs):
    xs = [x for x in xs if x is not None]
    return (sum(1 for x in xs if x > 0) / len(xs) * 100) if xs else None


def summarize(records, model_key):  # model_key = 'dec_v2' or 'dec_v4'
    lines = []
    for name, h in HORIZONS:
        mat = [r for r in records if r.get(name) is not None]
        buy = [r for r in mat if r.get(model_key) in ("BUY", "STRONG BUY")]
        mkt = _mean([r[name] for r in mat])
        b = _mean([r[name] for r in buy])
        hit = _hit([r[name] for r in buy])
        excess = (b - mkt) if (b is not None and mkt is not None) else None
        net = (b - ROUND_TRIP_COST) if b is not None else None
        ndays = len(set(r["signal_date"] for r in buy))
        lines.append({
            "horizon": name, "buy_n": len(buy), "buy_days": ndays,
            "buy_mean": b, "hit_rate": hit, "market_mean": mkt,
            "excess": excess, "buy_minus_cost": net,
        })
    return lines


def print_table(title, lines):
    log.info("\n" + "=" * 78 + "\n### %s\n" + "=" * 78, title)
    log.info("%-8s %6s %6s %10s %8s %12s %10s %12s",
             "horizon", "BUY n", "days", "BUY TB%", "hit%", "market TB%", "excess%", "BUY-phí%")
    for L in lines:
        def f(x, p=2):
            return "-" if x is None else f"{x:+.{p}f}"
        log.info("%-8s %6d %6d %10s %8s %12s %10s %12s",
                 L["horizon"], L["buy_n"], L["buy_days"],
                 f(L["buy_mean"]), ("-" if L["hit_rate"] is None else f"{L['hit_rate']:.1f}"),
                 f(L["market_mean"]), f(L["excess"]), f(L["buy_minus_cost"]))


def write_csv(records, sv2, sv4):
    import csv
    detail = os.path.join(OUTPUT_DIR, "backtest_v2v4_report.csv")
    with open(detail, "w", newline="", encoding="utf-8") as fh:
        cols = ["signal_date", "symbol", "regime", "dec_v2", "score_v2",
                "dec_v4", "score_v4", "ret_1d", "ret_3d", "ret_5d", "ret_10d",
                "_fidelity_flow_neutralized", "_fidelity_regime"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in records:
            w.writerow(r)
    summ = os.path.join(OUTPUT_DIR, "backtest_v2v4_summary.csv")
    with open(summ, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "horizon", "buy_n", "buy_days", "buy_mean",
                    "hit_rate", "market_mean", "excess", "buy_minus_cost"])
        for model, lines in [("V2.3", sv2), ("V4", sv4)]:
            for L in lines:
                w.writerow([model, L["horizon"], L["buy_n"], L["buy_days"],
                            L["buy_mean"], L["hit_rate"], L["market_mean"],
                            L["excess"], L["buy_minus_cost"]])
    log.info("\nĐã ghi: %s  và  %s", detail, summ)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=100, help="số ngày giao dịch backtest")
    ap.add_argument("--fetch-length", default="16M", help="độ dài history fetch (warmup TA + forward)")
    args = ap.parse_args()

    log.warning("\n" + "!" * 78)
    log.warning("FIDELITY: order-flow & FF-intraday TRUNG HOÀ (không tái tạo được quá khứ).")
    log.warning("          fundamental = số hiện tại (look-ahead nhẹ). regime = breadth-only.")
    log.warning("          ⇒ đây là backtest XẤP XỈ 'model trừ flow/FF', không phải replay hoàn hảo.")
    log.warning("!" * 78 + "\n")

    records = run_backtest(args.days, args.fetch_length)
    if not records:
        log.error("Không có record — kiểm tra fetch/universe.")
        return
    ndays = len(set(r["signal_date"] for r in records))
    log.info("\nTổng: %d (mã,ngày) trên %d phiên có forward.", len(records), ndays)

    sv2 = summarize(records, "dec_v2")
    sv4 = summarize(records, "dec_v4")
    print_table("V2.3 — rổ BUY (đã trừ phí %.2f%%)" % ROUND_TRIP_COST, sv2)
    print_table("V4   — rổ BUY (đã trừ phí %.2f%%)" % ROUND_TRIP_COST, sv4)
    write_csv(records, sv2, sv4)

    log.warning("\nNhắc lại: V4 ở đây thiếu flow/FF (weight flow 0.27) → đọc kết quả như CẬN DƯỚI, "
                "không phải hiệu năng đầy đủ của V4 production.")


if __name__ == "__main__":
    main()
