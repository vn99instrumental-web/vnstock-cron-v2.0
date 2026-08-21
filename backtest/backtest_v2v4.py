#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
backtest_v2v4.py  —  Backtest re-score V2.3 & V4 trên N ngày lịch sử (Cách A)
                     [BẢN 2 — vá theo log run 87987667376]
================================================================================
Tái dùng NGUYÊN hàm chấm điểm của repo (score_symbol_v2 / score_symbol_v4) +
hàm dựng feature (build_one/get_ta/get_snapshot). Chỉ CHẶN tầng fetch giá để
feature chỉ "thấy" nến ≤ ngày t. ⇒ phần QUYẾT ĐỊNH đúng 100% math model.

── ĐÃ VÁ so với bản 1 (nguyên nhân bị huỷ ở phút 30) ──────────────────────────
  [1] FIX CHÍ MẠNG: finance cache. Bản 1 dò sai path → mỗi mã lazy-fetch tài
      chính ~13s → ngày 1 chưa xong đã hết 30' timeout. Nay nạp ĐÚNG như pipeline:
      load_json("finance/cache.json")["symbols"]  → cache HIT, 0 fetch trong vòng.
  [2] BARS CACHE: ghi/nạp backtest_output/dataset.parquet (đúng path workflow đang
      cache) → lần chạy sau KHÔNG fetch lại 130 mã.
  [3] GHI CSV TĂNG DẦN + flush mỗi ngày → job bị huỷ giữa chừng VẪN còn CSV dùng được.
  [4] --max-minutes: tự dừng êm trước timeout (ghi xong summary) thay vì bị kill.
  [5] --offset để CHIA NHỎ (mỗi job vài chục ngày) + --summarize-only để gộp CSV.

── GIỚI HẠN TRUNG THỰC (không né được — in đỏ đầu report) ─────────────────────
  • order-flow & FF-intraday TRUNG HOÀ (dữ liệu tick không có cho quá khứ). flow
    có weight 0.27 khung TRADE V4 ⇒ đọc kết quả V4 như CẬN DƯỚI ("model trừ flow").
  • fundamental = số hiện tại (ratio_summary không point-in-time) → look-ahead nhẹ.
  • regime = breadth-only (index_raw = breadth_raw); hysteresis replay tuần tự.

── TỐC ĐỘ ─────────────────────────────────────────────────────────────────────
  Sau khi finance đã cache: mỗi ngày ≈ 130 mã × ~0.4s (recompute TA) ≈ 50–60s.
  ⇒ 100 ngày ≈ 90 phút. CÁCH CHẠY:
    • Nâng `timeout-minutes` của job lên ~120, chạy 1 phát:  --days 100
    • HOẶC chia nhỏ (giữ timeout 30'):  4 job  --days 30 --offset 0/30/60/90
      rồi gộp:  --summarize-only backtest_output/detail.csv
================================================================================
"""
import os
import sys
import time
import argparse
import logging
import traceback
from collections import defaultdict, Counter

os.environ.setdefault("VNSTOCK_INTERACTIVE", "0")
os.environ.setdefault("VNSTOCK_LANGUAGE", "en")
os.environ.setdefault("PREFETCH_ENABLED", "0")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backtest_v2v4")

# ── code THẬT của repo ────────────────────────────────────────────────────────
import steps.v2f_step_snapshot as SNAP
from steps.v2f_step_scoring import score_symbol_v2
from steps.v2f_step_scoring_v4 import (
    score_symbol_v4, _compute_breadth, _apply_hysteresis,
    factor_caps, active_signals, _augment_caps, validate_registry, gate_for,
)
from utils.regime_v42 import classify_regime_breadth, more_bearish
from utils.cache import load_json as repo_load_json
try:
    from steps.v2f_step_scoring_v4 import MIN_BREADTH_N
except Exception:
    MIN_BREADTH_N = 30
try:
    from utils.v2f_universe import get_universe
except Exception:
    get_universe = None
from config import OUTPUT_DIR  # noqa

ROUND_TRIP_COST = 0.40
HORIZONS = [("ret_1d", 1), ("ret_3d", 3), ("ret_5d", 5), ("ret_10d", 10)]
BT_DIR = os.path.join(OUTPUT_DIR, "..", "backtest_output")
BT_DIR = os.path.abspath(BT_DIR)
os.makedirs(BT_DIR, exist_ok=True)
BARS_PARQUET = os.path.join(BT_DIR, "dataset.parquet")
DETAIL_CSV = os.path.join(BT_DIR, "detail.csv")
SUMMARY_CSV = os.path.join(BT_DIR, "summary.csv")

BARS = {}
_REAL_QUOTE = SNAP.Quote
_AS_OF = None

# ══════════════════════════════════════════════════════════════════════════
# BARS: fetch 1 lần + cache parquet
# ══════════════════════════════════════════════════════════════════════════
def _norm_hist(df):
    import pandas as pd
    if df is None or getattr(df, "empty", True):
        return None
    df = df.copy()
    tcol = "time" if "time" in df.columns else ("date" if "date" in df.columns else None)
    if tcol is None:
        return None
    df["time"] = pd.to_datetime(df[tcol]).dt.normalize()
    keep = [c for c in ["time", "open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].sort_values("time").reset_index(drop=True)


def save_bars_parquet():
    try:
        import pandas as pd
        frames = []
        for sym, df in BARS.items():
            d = df.copy(); d["symbol"] = sym; frames.append(d)
        if frames:
            pd.concat(frames, ignore_index=True).to_parquet(BARS_PARQUET, index=False)
            log.info("💾 bars → %s (%d mã)", BARS_PARQUET, len(BARS))
    except Exception as e:
        log.warning("Không ghi được parquet (%s) — bỏ qua cache bars.", e)


def load_bars_parquet(symbols):
    try:
        import pandas as pd
        if not os.path.exists(BARS_PARQUET):
            return False
        big = pd.read_parquet(BARS_PARQUET)
        big["time"] = pd.to_datetime(big["time"]).dt.normalize()
        got = 0
        for sym, g in big.groupby("symbol"):
            BARS[sym] = g.drop(columns="symbol").sort_values("time").reset_index(drop=True)
            got += 1
        need = set(list(symbols) + ["VNINDEX"])
        miss = [s for s in need if s not in BARS]
        if miss:
            log.info("parquet thiếu %d mã (%s…) → sẽ fetch bù.", len(miss), ",".join(miss[:5]))
            return False
        log.info("♻️  Nạp bars từ cache parquet: %d mã (bỏ qua fetch).", got)
        return True
    except Exception as e:
        log.warning("Đọc parquet lỗi (%s) → fetch lại.", e)
        return False


def fetch_all_bars(symbols, fetch_length):
    if load_bars_parquet(symbols):
        return
    allsyms = list(symbols) + ["VNINDEX"]
    for i, sym in enumerate(allsyms):
        if sym in BARS:
            continue
        try:
            df = _REAL_QUOTE(source="VCI", symbol=sym).history(length=fetch_length, interval="1D")
            nd = _norm_hist(df)
            if nd is not None and len(nd) >= 30:
                BARS[sym] = nd
                log.info("  [%d/%d] %s: %d nến (%s → %s)", i + 1, len(allsyms), sym, len(nd),
                         nd['time'].iloc[0].date(), nd['time'].iloc[-1].date())
            else:
                log.warning("  %s: không đủ nến (bỏ)", sym)
        except Exception as e:
            log.warning("  %s: fetch lỗi %s", sym, e)
        time.sleep(0.30)
    save_bars_parquet()


# ══════════════════════════════════════════════════════════════════════════
# SHIM AS-OF + trung hoà flow/FF
# ══════════════════════════════════════════════════════════════════════════
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

    def intraday(self, *a, **k):
        import pandas as pd
        return pd.DataFrame()


def _neutral_flow(symbol, *a, **kw):
    return {
        "symbol": symbol,
        "_of_buy_count": 0, "_of_sell_count": 0, "_of_total_trades": 0,
        "_of_avg_size": None, "_of_distribution": None,
        "of_bp": None, "order_flow_score": 0,
        "ff_net_val_5d": 0, "ff_intra_flag_pts": 0, "ff_room": None,
        "_backtest_flow_neutralized": True,
    }


# ══════════════════════════════════════════════════════════════════════════
# CTX / REGIME (repo helpers) + replay hysteresis
# ══════════════════════════════════════════════════════════════════════════
def build_ctx_and_regime(rows, as_of, index_regime_override=None):
    ctx = {"_snap_time": as_of.strftime("%Y-%m-%d 15:00"), "_backtest": True}
    brd = _compute_breadth(rows)
    if brd.get("n", 0) >= MIN_BREADTH_N:
        breadth_raw = classify_regime_breadth(
            brd["share_50"], brd["share_200"], brd["med_c5"], brd["med_c20"])["regime_raw"]
    else:
        breadth_raw = "UNKNOWN"
    index_raw = index_regime_override or breadth_raw
    raw_regime = more_bearish(index_raw, breadth_raw)
    regime, _ = _apply_hysteresis(raw_regime, as_of.strftime("%Y-%m-%d"))
    div = breadth_raw not in (index_raw, "UNKNOWN")
    for r in rows:
        r["_regime"] = regime
        r["_ctx_regime"] = regime
    return ctx, regime, raw_regime, div, brd


# ══════════════════════════════════════════════════════════════════════════
# LOADERS
# ══════════════════════════════════════════════════════════════════════════
def load_universe():
    if get_universe:
        try:
            u = get_universe()
            out = []
            for item in u:
                if isinstance(item, (list, tuple)):
                    out.append((item[0], item[1] if len(item) > 1 else "VN100"))
                elif isinstance(item, dict):
                    out.append((item.get("symbol"), item.get("group", "VN100")))
                elif isinstance(item, str):
                    out.append((item, "VN100"))
            out = [(s, g) for s, g in out if s]
            if out:
                return out
        except Exception:
            log.warning("get_universe lỗi → fallback ledger.")
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
    import json
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
    log.warning("Không thấy industry_map → rỗng (vài sub-score ngành trung tính).")
    return []


def load_fin_cache():
    # ĐÚNG như pipeline (v2f_step_snapshot.py dòng 954-956)
    raw = repo_load_json("finance/cache.json") or {}
    fc = raw.get("symbols", raw) if isinstance(raw, dict) else {}
    log.info("Finance cache: %d symbols loaded", len(fc))
    return fc


def trading_dates_from_vnindex(days, offset=0):
    idx = BARS.get("VNINDEX")
    if idx is None or idx.empty:
        raise SystemExit("Thiếu nến VNINDEX.")
    all_dates = list(idx["time"])
    usable = all_dates[:-10] if len(all_dates) > 10 else []
    if offset:
        usable = usable[:-offset] if offset < len(usable) else []
    return [d.date() for d in usable[-days:]]


def fwd_returns(symbol, as_of):
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
        out[name] = ((float(df["close"].iloc[j]) / c0 - 1.0) * 100.0) if (j < len(df) and c0) else None
    return out


# ══════════════════════════════════════════════════════════════════════════
# VÒNG BACKTEST (ghi CSV tăng dần)
# ══════════════════════════════════════════════════════════════════════════
def run_backtest(days, fetch_length, offset, max_minutes):
    import csv
    validate_registry()
    caps = _augment_caps({hz: factor_caps(hz) for hz in ("trade", "hold")})
    actives = {hz: active_signals(hz) for hz in ("trade", "hold")}

    universe = load_universe()
    symbols = [s for s, _ in universe]
    group_of = {s: g for s, g in universe}
    log.info("Universe: %d mã", len(symbols))

    log.info("=== BARS (%s) ===", fetch_length)
    fetch_all_bars(symbols, fetch_length)
    if "VNINDEX" not in BARS:
        raise SystemExit("Không có VNINDEX.")

    industry_map = load_industry_map()
    fin_cache = load_fin_cache()

    # reset state hysteresis để replay sạch
    st = os.path.join(OUTPUT_DIR, "v2f_v4_regime_state.json")
    if os.path.exists(st):
        os.remove(st)

    dates = trading_dates_from_vnindex(days, offset)
    log.info("=== BACKTEST %d ngày (offset %d): %s → %s ===",
             len(dates), offset, dates[0], dates[-1])

    global _AS_OF
    SNAP.Quote = _AsOfQuote
    _real_get_flow = SNAP.get_flow
    SNAP.get_flow = _neutral_flow

    # ── CSV mở sẵn, ghi header, flush mỗi ngày ──
    append = os.path.exists(DETAIL_CSV) and offset > 0
    fh = open(DETAIL_CSV, "a" if append else "w", newline="", encoding="utf-8")
    cols = ["signal_date", "symbol", "regime", "dec_v2", "score_v2", "dec_v4", "score_v4",
            "ret_1d", "ret_3d", "ret_5d", "ret_10d",
            "_fidelity_flow_neutralized", "_fidelity_regime"]
    writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
    if not append:
        writer.writeheader()

    records = []
    t_start = time.time()
    try:
        for di, d in enumerate(dates):
            if max_minutes and (time.time() - t_start) / 60.0 >= max_minutes:
                log.warning("⏱️  Chạm --max-minutes=%s → dừng êm ở ngày %d/%d. CSV đã lưu tới đây.",
                            max_minutes, di, len(dates))
                break
            t_day = time.time()
            _AS_OF = d
            rows = []
            for sym in symbols:
                if sym not in BARS:
                    continue
                try:
                    r = SNAP.build_one(sym, group_of.get(sym, "VN100"), market_open=False,
                                       industry_map=industry_map, fin_cache=fin_cache)
                    if r and not r.get("error") and r.get("price") is not None:
                        rows.append(r)
                except Exception:
                    log.debug("build_one %s @%s:\n%s", sym, d, traceback.format_exc())
            if len(rows) < MIN_BREADTH_N:
                log.warning("  %s: %d mã — bỏ ngày.", d, len(rows))
                continue

            ctx, regime, raw_regime, div, brd = build_ctx_and_regime(rows, d)
            day_recs = []
            for r in rows:
                sym = r["symbol"]
                try:
                    v2 = score_symbol_v2(r, ctx, {}, {})
                    dec_v2, sc_v2 = v2.get("decision"), v2.get("total_score")
                except Exception:
                    dec_v2, sc_v2 = None, None
                try:
                    v4 = score_symbol_v4(dict(r), ctx, caps, actives, regime, raw_regime,
                                         ctx.get("market_regime_v42", "UNKNOWN"),
                                         regime_divergence=div)
                    dec_v4, sc_v4 = v4.get("decision"), v4.get("score_trade")
                except Exception:
                    log.debug("v4 %s @%s:\n%s", sym, d, traceback.format_exc())
                    dec_v4, sc_v4 = None, None
                rec = {"signal_date": d.isoformat(), "symbol": sym, "regime": regime,
                       "dec_v2": dec_v2, "score_v2": sc_v2, "dec_v4": dec_v4, "score_v4": sc_v4,
                       "_fidelity_flow_neutralized": True, "_fidelity_regime": "breadth_only"}
                rec.update(fwd_returns(sym, d))
                day_recs.append(rec)

            for rec in day_recs:
                writer.writerow(rec)
            fh.flush()
            records.extend(day_recs)

            b2 = sum(1 for x in day_recs if x["dec_v2"] in ("BUY", "STRONG BUY"))
            b4 = sum(1 for x in day_recs if x["dec_v4"] in ("BUY", "STRONG BUY"))
            log.info("  [%d/%d] %s regime=%s | mã=%d | BUY v2=%d v4=%d | %.1fs",
                     di + 1, len(dates), d, regime, len(day_recs), b2, b4, time.time() - t_day)
    finally:
        SNAP.Quote = _REAL_QUOTE
        SNAP.get_flow = _real_get_flow
        fh.close()
    log.info("CSV chi tiết: %s (%d dòng lần này)", DETAIL_CSV, len(records))
    return records


# ══════════════════════════════════════════════════════════════════════════
# TỔNG HỢP
# ══════════════════════════════════════════════════════════════════════════
def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _hit(xs):
    xs = [x for x in xs if x is not None]
    return (sum(1 for x in xs if x > 0) / len(xs) * 100) if xs else None


def summarize(records, model_key):
    lines = []
    for name, h in HORIZONS:
        mat = [r for r in records if r.get(name) is not None]
        buy = [r for r in mat if r.get(model_key) in ("BUY", "STRONG BUY")]
        mkt = _mean([r[name] for r in mat])
        b = _mean([r[name] for r in buy])
        excess = (b - mkt) if (b is not None and mkt is not None) else None
        net = (b - ROUND_TRIP_COST) if b is not None else None
        lines.append({"horizon": name, "buy_n": len(buy),
                      "buy_days": len(set(r["signal_date"] for r in buy)),
                      "buy_mean": b, "hit_rate": _hit([r[name] for r in buy]),
                      "market_mean": mkt, "excess": excess, "buy_minus_cost": net})
    return lines


def print_table(title, lines):
    log.info("\n" + "=" * 84)
    log.info("### %s", title)
    log.info("=" * 84)
    log.info("%-8s %6s %6s %10s %8s %12s %10s %12s",
             "horizon", "BUY n", "days", "BUY TB%", "hit%", "market%", "excess%", "BUY-phí%")
    for L in lines:
        f = lambda x: "-" if x is None else f"{x:+.2f}"
        log.info("%-8s %6d %6d %10s %8s %12s %10s %12s",
                 L["horizon"], L["buy_n"], L["buy_days"], f(L["buy_mean"]),
                 ("-" if L["hit_rate"] is None else f"{L['hit_rate']:.1f}"),
                 f(L["market_mean"]), f(L["excess"]), f(L["buy_minus_cost"]))


def write_summary_csv(sv2, sv4):
    import csv
    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "horizon", "buy_n", "buy_days", "buy_mean", "hit_rate",
                    "market_mean", "excess", "buy_minus_cost"])
        for model, lines in [("V2.3", sv2), ("V4", sv4)]:
            for L in lines:
                w.writerow([model, L["horizon"], L["buy_n"], L["buy_days"], L["buy_mean"],
                            L["hit_rate"], L["market_mean"], L["excess"], L["buy_minus_cost"]])
    log.info("Bảng tổng hợp: %s", SUMMARY_CSV)


def load_detail_csv(path):
    import csv
    recs = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            for k in ("ret_1d", "ret_3d", "ret_5d", "ret_10d", "score_v2", "score_v4"):
                v = row.get(k)
                row[k] = (float(v) if v not in (None, "", "None") else None)
            recs.append(row)
    return recs


def report(records):
    ndays = len(set(r["signal_date"] for r in records))
    log.info("\nTổng: %d (mã,ngày) trên %d phiên.", len(records), ndays)
    sv2 = summarize(records, "dec_v2")
    sv4 = summarize(records, "dec_v4")
    print_table("V2.3 — rổ BUY (đã trừ phí %.2f%%)" % ROUND_TRIP_COST, sv2)
    print_table("V4   — rổ BUY (đã trừ phí %.2f%%)" % ROUND_TRIP_COST, sv4)
    write_summary_csv(sv2, sv4)
    log.warning("\nNhắc: V4 thiếu flow/FF (weight flow 0.27) → đọc như CẬN DƯỚI, không phải V4 đầy đủ.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=100)
    ap.add_argument("--offset", type=int, default=0, help="bỏ qua N ngày mới nhất (để chia job)")
    ap.add_argument("--fetch-length", default="16M")
    ap.add_argument("--max-minutes", type=float, default=0, help="tự dừng êm trước timeout (0=tắt)")
    ap.add_argument("--summarize-only", default="", help="chỉ gộp & in summary từ detail.csv")
    args = ap.parse_args()

    if args.summarize_only:
        report(load_detail_csv(args.summarize_only))
        return

    log.warning("\n" + "!" * 84)
    log.warning("FIDELITY: order-flow & FF-intraday TRUNG HOÀ | fundamental hiện tại | regime breadth-only.")
    log.warning("          ⇒ backtest XẤP XỈ 'V4 trừ flow/FF', không phải replay hoàn hảo.")
    log.warning("!" * 84 + "\n")

    records = run_backtest(args.days, args.fetch_length, args.offset, args.max_minutes)
    if not records:
        log.error("Không có record — kiểm fetch/universe/finance cache.")
        # vẫn thử gộp CSV nếu có (trường hợp chạy chồng offset)
        if os.path.exists(DETAIL_CSV):
            report(load_detail_csv(DETAIL_CSV))
        return
    # gộp TOÀN BỘ detail.csv (kể cả các offset trước) để summary đầy đủ
    report(load_detail_csv(DETAIL_CSV) if os.path.exists(DETAIL_CSV) else records)


if __name__ == "__main__":
    main()
