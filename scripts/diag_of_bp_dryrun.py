#!/usr/bin/env python3
"""
diag_of_bp_dryrun.py  —  DRY-RUN READ-ONLY cho cờ OF buy-pressure (of_bp_pts)
============================================================================
KHÔNG ghi file, KHÔNG commit, KHÔNG đụng ledger. Chỉ đọc output/v2f_signals*.json
HIỆN CÓ, tính of_bp_pts theo helper, rồi báo tác động TRƯỚC khi merge vào cron:

  1. Coverage input (bao nhiêu mã có đủ _of_* để tính).
  2. Tần suất cờ bật (+4 / -4 / 0) — kỳ vọng ~1-2% như ff_intra.
  3. Số mã bị ĐỔI DECISION khi cộng ±4 (mô phỏng: score_mới = score_cũ + pts,
     capped ±100, rồi map lại band). Liệt kê để soi bằng mắt.

Chạy:
  - Qua debug.yml: workflow_dispatch, input `script` = diag_of_bp_dryrun.py
  - Local:         python scripts/diag_of_bp_dryrun.py
"""
import json
import os
import sys

# cho phép import utils/ khi chạy từ scripts/
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.of_buy_pressure import buy_pressure_pts, BP_CAP  # noqa: E402

OUT = os.path.join(_ROOT, "output")


def _decide_v4(score):
    from utils.v2f_registry import THRESHOLDS
    for cut, name in THRESHOLDS:
        if score >= cut:
            return name
    return THRESHOLDS[-1][1]


def _decide_v23(score):
    if score >= 80:   return "STRONG BUY"
    if score >= 40:   return "BUY"
    if score >= -15:  return "NEUTRAL"
    if score >= -40:  return "SELL"
    return "STRONG SELL"


def _pts(row):
    return buy_pressure_pts(row.get("_of_buy_count"), row.get("_of_sell_count"),
                            row.get("_of_total_trades"), row.get("vol_ma_ratio"))


def run_one(label, filename, score_field, decide):
    path = os.path.join(OUT, filename)
    if not os.path.exists(path):
        print(f"[{label}] KHÔNG thấy {filename} — bỏ qua.")
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    rows = data if isinstance(data, list) else list(data.values())

    n = len(rows)
    have_input = sum(1 for r in rows if r.get("_of_buy_count") is not None)
    pos = neg = 0
    flips = []
    for r in rows:
        p = _pts(r)
        if p > 0: pos += 1
        elif p < 0: neg += 1
        if p == 0:
            continue
        sc = r.get(score_field)
        if sc is None:
            continue
        new = max(-100.0, min(100.0, sc + p))
        old_dec = r.get("decision")
        new_dec = decide(new)
        if new_dec != old_dec:
            flips.append((r.get("symbol"), sc, new, old_dec, new_dec, p))

    fired = pos + neg
    print(f"\n===== [{label}]  {filename} =====")
    print(f"  Tổng mã: {n} | có đủ input _of_*: {have_input} ({have_input/n*100:.0f}%)")
    print(f"  Cờ bật: {fired} ({fired/n*100:.1f}%)  ->  +{BP_CAP}: {pos} | -{BP_CAP}: {neg}")
    print(f"  Đổi decision do cờ: {len(flips)} / {fired if fired else 1} mã bật")
    if flips:
        print("  Chi tiết mã đổi decision:")
        for sym, old, new, od, nd, p in flips:
            print(f"    {sym:6} {p:+d}  score {old:+.1f} -> {new:+.1f}   [{od}] -> [{nd}]")
    else:
        print("  (không mã nào đổi band — ±%d quá nhỏ so với vị trí điểm)" % BP_CAP)


def main():
    print("DRY-RUN OF buy-pressure — READ-ONLY, không ghi file/ledger.")
    run_one("V2.3", "v2f_signals.json",    "total_score", _decide_v23)
    run_one("V4",   "v2f_signals_v4.json", "score_trade", _decide_v4)
    print("\nXong. Không có gì được ghi. Kiểm tần suất (~1-2%?) + các mã đổi decision "
          "có hợp lý không trước khi merge vào cron.")


if __name__ == "__main__":
    main()
