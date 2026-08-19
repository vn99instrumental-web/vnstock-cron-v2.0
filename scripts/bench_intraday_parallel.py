#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bench_intraday_parallel.py — LOAD TEST cho Option B. Read-only (không ghi output
production, không commit). NHƯNG CÓ THẬT SỰ ĐẤM API VCI → xem cảnh báo dưới.
================================================================================
MỤC ĐÍCH:
    Đo xem có thể fetch intraday(page_size=10000) SONG SONG (nhiều worker) mà
    KHÔNG bị 429/mất data hay không — để quyết định Option B (dồn intraday về 1
    lần fetch dùng chung, chạy song song) có khả thi không.

    Hiện tại order_flow chạy ĐƠN LUỒNG (workers=1, interval=0.5s) đúng vì
    intraday(10000) là endpoint NẶNG, chạy song song từng gây bão hoà 429
    (ghi trong header utils/vci_throttle.py). Script này kiểm lại giả thuyết đó
    một cách có số liệu, thay vì đoán.

⚠️  CẢNH BÁO VẬN HÀNH — ĐỌC TRƯỚC KHI CHẠY:
    - Script này gọi intraday(10000) cho TOÀN universe, lặp lại cho mỗi cấu hình
      → tốn quota VCI thật. KHÔNG chạy trong vòng ~5 phút quanh 1 run intraday
      production (09:30/10:30/11:30/13:30/14:30 ICT) để tránh tranh quota.
    - Nên chạy vào khoảng TRỐNG giữa 2 run production, hoặc cuối phiên.
    - intraday(10000) ngoài giờ vẫn trả tape đã đóng của phiên hôm nay → test tải
      vẫn hợp lệ ngoài giờ (chỉ cần hôm nay CÓ phiên giao dịch).

CÁCH ĐO (giữ nguyên circuit-breaker như production để số liệu SÁT thực tế):
    Mỗi cấu hình (workers, min_interval):
      - reset circuit breaker + counter
      - chạy fetch toàn universe qua ThreadPoolExecutor
      - đếm: ok / empty / fail / 429 / missing; đo wall-time; tính fail-rate
    Giữa 2 cấu hình: nghỉ COOLDOWN giây cho VCI hồi.

ĐỌC KẾT QUẢ:
    Chọn cấu hình NHANH NHẤT mà: 429=0, missing=0, completeness=100%.
    Nếu mọi cấu hình >1 worker đều sinh 429 → Option B KHÔNG an toàn, giữ workers=1
    (tức chỉ nên làm Option A: dedup, không song song hoá).

DISPATCH:
    debug.yml → input script = scripts/bench_intraday_parallel.py
    Tuỳ chọn qua env:
      BENCH_CONFIGS = "1:0.5,2:0.4,3:0.35"   (workers:interval, phẩy ngăn cách)
                      mặc định như trên (thang từ an toàn → mạnh dần)
      BENCH_LIMIT   = "130"  giới hạn số mã (mặc định: cả universe). Lần đầu nên
                      để nhỏ (vd 40) để dò nhẹ trước khi test full.
      BENCH_COOLDOWN= "25"   nghỉ giữa 2 cấu hình (giây)
      BENCH_PAGESIZE= "10000" giống order_flow production
"""
import os
import sys
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from vnstock_data import Quote

from utils.helpers import now_ict, is_market_open
from utils.v2f_universe import build_v2f_universe
from utils import vci_throttle as T

logging.basicConfig(level=logging.WARNING,   # WARNING để log gọn khi chạy nhiều mã
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bench_intraday")

PAGESIZE = int(os.environ.get("BENCH_PAGESIZE", "10000"))
COOLDOWN = int(os.environ.get("BENCH_COOLDOWN", "25"))


def _parse_configs() -> list[tuple[int, float]]:
    raw = os.environ.get("BENCH_CONFIGS", "1:0.5,2:0.4,3:0.35").strip()
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            w, iv = part.split(":")
            out.append((int(w), float(iv)))
        except Exception:
            log.warning(f"bỏ qua config sai định dạng: {part!r}")
    return out or [(1, 0.5)]


def _load_symbols() -> list[str]:
    jobs, _ = build_v2f_universe()
    syms = [s for s, _g in jobs]
    lim = os.environ.get("BENCH_LIMIT", "").strip()
    if lim:
        try:
            syms = syms[: int(lim)]
        except Exception:
            pass
    return syms


def _fetch_one(symbol: str) -> str:
    """
    Trả nhãn kết quả: 'ok' | 'empty' | '429' | 'fail'.
    Đi qua throttle() như production; khi 429 gọi note_rate_limited() để bật
    circuit-breaker chung (giữ hành vi thật). KHÔNG dùng vci_safe_run vì nó nuốt
    exception → không đếm được 429.
    """
    # Kill switch bật (blackout) → bail, coi như fail.
    if T.is_blocked():
        return "fail"
    T.throttle()
    try:
        df = Quote(source="VCI", symbol=symbol).intraday(page_size=PAGESIZE)
        if df is None or getattr(df, "empty", True):
            return "empty"
        return "ok"
    except Exception as e:
        if T.is_rate_limited(e):
            T.note_rate_limited()
            return "429"
        if T.is_premarket_block(e):
            return "fail"
        return "fail"


def _run_config(symbols: list[str], workers: int, interval: float) -> dict:
    # Reset trạng thái throttle giữa các cấu hình để số liệu độc lập.
    T.reset_kill_switch()
    T.set_min_interval(interval)

    counts = {"ok": 0, "empty": 0, "429": 0, "fail": 0}
    seen = set()
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_one, s): s for s in symbols}
        for fut in as_completed(futs):
            s = futs[fut]
            seen.add(s)
            try:
                label = fut.result()
            except Exception:
                label = "fail"
            counts[label] = counts.get(label, 0) + 1
    wall = time.monotonic() - t0

    n = len(symbols)
    missing = n - len(seen)
    got = counts["ok"] + counts["empty"]        # có phản hồi (kể cả rỗng)
    completeness = got / n * 100 if n else 0.0
    real_fail = counts["429"] + counts["fail"]
    fail_rate = real_fail / n * 100 if n else 0.0

    return {
        "workers": workers, "interval": interval, "wall": wall,
        "ok": counts["ok"], "empty": counts["empty"],
        "n429": counts["429"], "fail": counts["fail"],
        "missing": missing, "completeness": completeness,
        "fail_rate": fail_rate, "n": n,
    }


def main():
    symbols = _load_symbols()
    configs = _parse_configs()
    mkt = is_market_open()

    print("=" * 90)
    print("BENCH intraday(page_size=%d) song song — Option B feasibility" % PAGESIZE)
    print(f"Thời điểm : {now_ict():%Y-%m-%d %H:%M:%S} ICT   (market_open={mkt})")
    print(f"Universe  : {len(symbols)} mã   Cooldown giữa config: {COOLDOWN}s")
    print(f"Configs   : {configs}   (workers:interval)")
    print("=" * 90)
    print("⚠️  Đảm bảo KHÔNG trùng ±5 phút quanh run intraday production.\n")

    results = []
    for i, (w, iv) in enumerate(configs):
        print("-" * 90)
        print(f"▶ Config {i+1}/{len(configs)}: workers={w}, interval={iv}s ...")
        r = _run_config(symbols, w, iv)
        results.append(r)
        print(f"  wall={r['wall']:.1f}s  ok={r['ok']}  empty={r['empty']}  "
              f"429={r['n429']}  fail={r['fail']}  missing={r['missing']}  "
              f"completeness={r['completeness']:.1f}%  fail_rate={r['fail_rate']:.1f}%")
        if i < len(configs) - 1:
            print(f"  nghỉ {COOLDOWN}s cho VCI hồi...")
            time.sleep(COOLDOWN)

    # ── Bảng tổng ──────────────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("BẢNG SO SÁNH")
    print("=" * 90)
    hdr = f"{'workers':>7} {'interval':>8} {'wall(s)':>8} {'429':>5} {'fail':>5} {'missing':>7} {'complete%':>9}"
    print(hdr)
    print("-" * 90)
    for r in results:
        print(f"{r['workers']:>7} {r['interval']:>8.2f} {r['wall']:>8.1f} "
              f"{r['n429']:>5} {r['fail']:>5} {r['missing']:>7} {r['completeness']:>8.1f}%")

    # ── Khuyến nghị tự động ────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("KHUYẾN NGHỊ")
    print("=" * 90)
    baseline = next((r for r in results if r["workers"] == 1), results[0])
    # Cấu hình "sạch": 429=0, missing=0, completeness=100
    clean = [r for r in results
             if r["n429"] == 0 and r["missing"] == 0 and r["completeness"] >= 99.9]
    if clean:
        best = min(clean, key=lambda r: r["wall"])
        saved = baseline["wall"] - best["wall"]
        print(f"✅ Cấu hình SẠCH nhanh nhất: workers={best['workers']}, "
              f"interval={best['interval']}s → wall={best['wall']:.1f}s")
        if best["workers"] > 1:
            print(f"   Nhanh hơn baseline (workers=1) ~{saved:.0f}s "
                  f"({baseline['wall']:.0f}s → {best['wall']:.0f}s).")
            print("   → Option B KHẢ THI ở cấu hình này. Vẫn nên benchmark lặp lại")
            print("     nhiều phiên/khung giờ trước khi đưa vào production.")
        else:
            print("   → Chỉ workers=1 là sạch. Option B (song song) CHƯA an toàn ở")
            print("     các cấu hình đã thử → nên dừng ở Option A (dedup, đơn luồng).")
    else:
        print("❌ KHÔNG cấu hình nào 'sạch' (đều có 429/missing).")
        print("   → Option B RỦI RO. Giữ workers=1; chỉ làm Option A (dedup).")
    print("=" * 90)


if __name__ == "__main__":
    main()
