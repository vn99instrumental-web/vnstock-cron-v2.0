"""
scripts/diag_hnx30_coverage.py — Kiểm tra HNX30 TRƯỚC khi gộp vào universe V2f
==============================================================================
MỤC ĐÍCH: trả lời 4 câu hỏi go/no-go trước khi sửa v2f_universe.py:

  Q1. HNX30 có lấy được qua Listing.symbols_by_group("HNX30") không? (count + sample)
  Q2. HNX30 có TRÙNG mã nào với VN100 không? (kỳ vọng: 0 — khác sàn HSX vs HNX)
  Q3. FF (foreign_trade VCI) có trả NET VALUE phân biệt per-symbol cho mã HNX
      không? (rủi ro chính — nếu rỗng/identical thì ff_score sẽ = 0 cho cả nhóm)
      + foreign room (fr_available_percentage / fr_room_percentage) có data không?
  Q4. Order-flow (intraday 10000) + TA (history 12M) có chạy cho mã HNX không,
      và TỐN THÊM bao nhiêu giây? (xác nhận budget — order_flow chạy workers=1)

MIRROR PRODUCTION (step_snapshot_v2.get_flow / get_ta):
  - FF      : Trading(symbol, source="VCI").foreign_trade(start=start_str(25), end=today_str())
              net_5d = net.sort_ASC.tail(5).sum() ; net_20d = net.sum()
              cột net fallback: fr_net_value_total → ... ; room: fr_available_percentage
  - OrderFlow: Quote(source="VCI", symbol).intraday(page_size=10000)
  - TA      : Quote(source="VCI", symbol).history(length="12M", interval="1D")
  Mọi call đi qua vci_safe_run / throttle (đồng nhất pipeline, an toàn quota).

CHẠY:
  python scripts/diag_hnx30_coverage.py
  qua debug.yml: input script = diag_hnx30_coverage

  Nên chạy TRONG GIỜ GD để có T+0 order-flow. FF + history vẫn hoạt động
  ngoài giờ (data lịch sử) → Q1/Q2/Q3 rút được kết luận cả ngoài giờ.

ENV overrides:
  DIAG_HNX_FF_LIMIT   = "0"   # số mã HNX30 test FF; 0 = TẤT CẢ (~30)
  DIAG_HNX_OF_SAMPLE  = "6"   # số mã test order-flow/TA + đo timing (đắt hơn)
  DIAG_VN100_GROUP    = "VN100"
  DIAG_HNX30_GROUP    = "HNX30"
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["VNSTOCK_INTERACTIVE"] = "0"
os.environ["VNSTOCK_LANGUAGE"]    = "en"
os.environ["MPLCONFIGDIR"]        = "/home/runner/.config/matplotlib"
os.makedirs("/home/runner/.vnstock",           exist_ok=True)
os.makedirs("/home/runner/.config/matplotlib", exist_ok=True)

import logging
import pandas as pd

from vnstock_data import Listing, Quote, Trading

from utils.helpers import now_ict, is_market_open, start_str, today_str
# Throttle riêng V2 — đồng nhất với pipeline (circuit breaker / kill switch / 429 guard)
from utils.vci_throttle import vci_safe_run, throttle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("diag_hnx30")

VN100_GROUP = os.environ.get("DIAG_VN100_GROUP", "VN100")
HNX30_GROUP = os.environ.get("DIAG_HNX30_GROUP", "HNX30")
FF_LIMIT    = int(os.environ.get("DIAG_HNX_FF_LIMIT", "0"))   # 0 = tất cả
OF_SAMPLE   = int(os.environ.get("DIAG_HNX_OF_SAMPLE", "6"))

# ── Cột mirror step_snapshot_v2.get_flow() ──
NET_COLS  = ["fr_net_value_total", "fr_net_value", "net_value", "net_val"]
BUY_COLS  = ["fr_buy_value_matched", "fr_buy_value", "buy_value", "buy_val"]
SELL_COLS = ["fr_sell_value_matched", "fr_sell_value", "sell_value", "sell_val"]
ROOM_COLS = ["fr_available_percentage", "fr_room_percentage",
             "fr_current_room", "fr_total_room"]
DATE_COLS = ("date", "time", "trading_date", "trade_date")


# =====================================================
# Helpers
# =====================================================
def _members(group: str) -> list:
    """Listing.symbols_by_group → list[str] upper. Mirror fetch_index_members."""
    res = vci_safe_run(
        f"symbols_by_group({group})",
        lambda: Listing(source="VCI").symbols_by_group(group=group),
    )
    if res is None:
        return []
    try:
        if isinstance(res, pd.Series):
            syms = res.dropna().astype(str).tolist()
        elif isinstance(res, pd.DataFrame):
            if res.empty:
                return []
            col = "symbol" if "symbol" in res.columns else res.columns[0]
            syms = res[col].dropna().astype(str).tolist()
        elif isinstance(res, (list, tuple)):
            syms = [str(s) for s in res]
        else:
            return []
    except Exception as e:
        log.warning(f"  parse {group} members lỗi: {e}")
        return []
    return [s.strip().upper() for s in syms if s and s.strip()]


def _pick(df: pd.DataFrame, candidates: list) -> str | None:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _net_metrics(df: pd.DataFrame):
    """Trả (net_5d, net_20d, rows, net_col) — y hệt step_snapshot_v2."""
    if df is None or df.empty:
        return None, None, 0, None
    df = df.copy()
    date_col = next((c for c in df.columns if c in DATE_COLS), None)
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.sort_values(date_col, ascending=True)

    net_col = _pick(df, NET_COLS)
    if net_col is None:
        bcol, scol = _pick(df, BUY_COLS), _pick(df, SELL_COLS)
        if bcol and scol:
            df["_net_"] = (
                pd.to_numeric(df[bcol], errors="coerce").fillna(0)
                - pd.to_numeric(df[scol], errors="coerce").fillna(0)
            )
            net_col = "_net_"
        else:
            return None, None, len(df), None

    net = pd.to_numeric(df[net_col], errors="coerce").dropna()
    if net.empty:
        return None, None, len(df), net_col
    return float(net.tail(5).sum()), float(net.sum()), len(net), net_col


def _room_pct(df: pd.DataFrame):
    """Foreign room utilization — lấy giá trị dòng cuối (mới nhất)."""
    if df is None or df.empty:
        return None, None
    df2 = df.copy()
    date_col = next((c for c in df2.columns if c in DATE_COLS), None)
    if date_col:
        df2[date_col] = pd.to_datetime(df2[date_col], errors="coerce")
        df2 = df2.sort_values(date_col, ascending=True)
    rcol = _pick(df2, ROOM_COLS)
    if rcol is None:
        return None, None
    val = pd.to_numeric(df2[rcol], errors="coerce").dropna()
    if val.empty:
        return None, rcol
    return float(val.iloc[-1]), rcol


# =====================================================
# Main
# =====================================================
def run():
    trading = is_market_open()
    log.info("=" * 70)
    log.info(f"DIAG HNX30 COVERAGE ({now_ict():%Y-%m-%d %H:%M:%S} ICT) — market_open={trading}")
    log.info("=" * 70)

    # ── Q1: lấy HNX30 + VN100 ──
    vn100 = set(_members(VN100_GROUP))
    hnx30 = _members(HNX30_GROUP)
    log.info(f"[Q1] {VN100_GROUP}: {len(vn100)} mã | {HNX30_GROUP}: {len(hnx30)} mã")
    log.info(f"     HNX30 sample: {hnx30[:15]}")
    if not hnx30:
        log.error("🚨 HNX30 RỖNG — symbols_by_group('HNX30') fail. Dừng, thử lại sau.")
        return

    # ── Q2: overlap ──
    overlap = sorted(set(hnx30) & vn100)
    log.info(f"[Q2] Trùng mã VN100 ∩ HNX30: {len(overlap)} {overlap if overlap else '(không có)'}")
    merged = list(vn100) + [s for s in hnx30 if s not in vn100]
    log.info(f"     Universe gộp (dedupe): {len(vn100)} + {len(merged)-len(vn100)} HNX30 mới "
             f"= {len(merged)} mã")

    # ── Q3: FF coverage trên HNX30 ──
    ff_targets = hnx30 if FF_LIMIT <= 0 else hnx30[:FF_LIMIT]
    log.info(f"\n[Q3] FF (foreign_trade VCI) trên {len(ff_targets)} mã HNX30 …")
    net5d_map: dict = {}
    room_ok = 0
    ff_times = []
    for sym in ff_targets:
        throttle()
        t0 = time.time()
        df = vci_safe_run(
            f"foreign_trade {sym}",
            lambda: Trading(symbol=sym, source="VCI").foreign_trade(
                start=start_str(25), end=today_str()),
        )
        dt = time.time() - t0
        ff_times.append(dt)
        n5, n20, rows, ncol = _net_metrics(df)
        room, rcol = _room_pct(df)
        net5d_map[sym] = n5
        if room is not None:
            room_ok += 1
        flag = "OK " if n5 is not None else "EMPTY"
        log.info(f"     {flag} {sym:5s} net5d={n5} net20d={n20} rows={rows} "
                 f"room={room}({rcol}) [{dt:.2f}s]")

    have = [v for v in net5d_map.values() if v is not None]
    distinct = len(set(have))
    log.info(f"     → FF data: {len(have)}/{len(ff_targets)} mã | "
             f"{distinct} giá trị net_5d KHÁC NHAU | room: {room_ok}/{len(ff_targets)} mã")

    # ── Q4: order-flow (intraday 10000) + TA (history 12M) + timing ──
    of_targets = ff_targets[:OF_SAMPLE]
    log.info(f"\n[Q4] Order-flow + TA trên sample {len(of_targets)} mã HNX30 …")
    intra_times, hist_times = [], []
    of_ok = hist_ok = 0
    for sym in of_targets:
        throttle()
        t0 = time.time()
        df_in = vci_safe_run(
            f"intraday {sym}",
            lambda: Quote(source="VCI", symbol=sym).intraday(page_size=10000),
        )
        intra_times.append(time.time() - t0)
        n_in = 0 if (df_in is None or df_in.empty) else len(df_in)
        if n_in > 0:
            of_ok += 1

        throttle()
        t1 = time.time()
        df_h = vci_safe_run(
            f"history {sym}",
            lambda: Quote(source="VCI", symbol=sym).history(length="12M", interval="1D"),
        )
        hist_times.append(time.time() - t1)
        n_h = 0 if (df_h is None or df_h.empty) else len(df_h)
        if n_h >= 200:           # cần ≥200 bar cho EMA200
            hist_ok += 1
        log.info(f"     {sym:5s} intraday_rows={n_in} hist_bars={n_h} "
                 f"(EMA200 {'OK' if n_h >= 200 else 'THIẾU'})")

    def _avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    avg_ff    = _avg(ff_times)
    avg_intra = _avg(intra_times)
    avg_hist  = _avg(hist_times)
    n_new     = len(merged) - len(vn100)   # số mã HNX30 thực sự thêm

    # snapshot: workers=5 (FF + intraday + history song song) → chia ~5
    est_snapshot = n_new * (avg_ff + avg_intra + avg_hist) / 5.0
    # order_flow: workers=1 (đọc lại ticks đã lưu, ~tuần tự) → dùng avg_intra làm proxy
    est_orderflow = n_new * avg_intra

    # ── Verdict ──
    log.info("\n" + "=" * 70)
    log.info("KẾT LUẬN")
    log.info("=" * 70)
    log.info(f"Q1 HNX30 lấy được     : {len(hnx30)} mã  → {'OK' if len(hnx30) >= 25 else '⚠️ ÍT BẤT THƯỜNG'}")
    log.info(f"Q2 Trùng VN100        : {len(overlap)} mã  → {'OK (không trùng)' if not overlap else '⚠️ CÓ TRÙNG — dedupe sẽ xử lý'}")
    log.info(f"Q3 FF có data         : {len(have)}/{len(ff_targets)} | distinct={distinct} | room={room_ok}/{len(ff_targets)}")
    log.info(f"Q4 OrderFlow/TA sample: intraday {of_ok}/{len(of_targets)} | EMA200-ready {hist_ok}/{len(of_targets)}")
    log.info(f"Timing TB/mã          : FF {avg_ff:.2f}s | intraday {avg_intra:.2f}s | history {avg_hist:.2f}s")
    log.info(f"Ước tính thêm {n_new} mã  : snapshot +~{est_snapshot:.0f}s | order_flow +~{est_orderflow:.0f}s")
    log.info("  (baseline log gần nhất: snapshot ~144s/100, order_flow ~144s/100 @ workers=1)")
    log.info("-" * 70)

    ff_ratio = (len(have) / len(ff_targets)) if ff_targets else 0
    go_ff = ff_ratio >= 0.8 and distinct >= max(2, int(len(have) * 0.8))
    go_of = (of_ok >= max(1, int(len(of_targets) * 0.8))
             and hist_ok >= max(1, int(len(of_targets) * 0.8)))

    if not have and not trading:
        log.info("⚠️ FF rỗng NHƯNG đang NGOÀI GIỜ GD — foreign_trade lấy data lịch sử nên")
        log.info("   đáng lẽ vẫn có. Thử lại 1 lần nữa; nếu vẫn rỗng → VCI không cover HNX.")
    elif go_ff and go_of:
        log.info("✅ GO — HNX30 đủ điều kiện gộp vào universe V2f:")
        log.info("   • Không trùng mã (hoặc đã dedupe) • FF per-symbol có data & phân biệt")
        log.info("   • intraday + history(EMA200) chạy được • timing trong budget cron giờ.")
        log.info("   → Bước tiếp: sửa v2f_universe.py thêm fetch_index_members('HNX30') + merge dedupe.")
    elif go_of and not go_ff:
        log.info("⚠️ ĐIỀU KIỆN MỘT PHẦN — TA/order-flow OK nhưng FF HNX yếu/identical.")
        log.info("   → Vẫn gộp được, NHƯNG nhóm ff cho mã HNX sẽ ~0 (validate_ff_data fail-safe).")
        log.info("   → Cân nhắc: gộp nhưng chấp nhận ff=0 cho HNX, hoặc giữ nguyên VN100.")
    else:
        log.info("🛑 NO-GO (tạm) — TA/order-flow hoặc FF không đạt cho mã HNX.")
        log.info("   → Xem chi tiết Q3/Q4 phía trên. Thử lại trong giờ GD trước khi quyết định.")
    log.info("=" * 70)


if __name__ == "__main__":
    run()
