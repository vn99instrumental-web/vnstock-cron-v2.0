"""
diag_buy_tpsl_forward.py — CHẤM ĐIỂM FORWARD CHO LỆNH BUY (read-only)
================================================================================
Trả lời đúng 1 câu hỏi: "Các lệnh BUY của V4, sau khi đủ tuổi, HIT TP hay HIT SL
nhiều hơn?" — đo bằng GIÁ CAO/THẤP từng phiên (field hit_tp1/hit_sl mà trọng tài
v2f_step_eval_predictions.py đã ghi), KHÔNG dùng giá đóng cửa.

NGUYÊN TẮC (khớp yêu cầu):
  1) CHỈ tính decision ∈ {BUY, STRONG BUY}. Bỏ NEUTRAL/SELL.
  2) Chỉ tin field TP/SL của trọng tài (hit_tp1 = có phiên high ≥ tp1;
     hit_sl = có phiên low ≤ stop). Same-bar chạm cả 2 → trọng tài đã giả định
     STOP trước (bảo thủ) — ở đây chỉ đọc kết quả, không đổi luật.
  3) DEDUP daily-last: 1 ngày có tới 6 run/mã (6 pred_id cùng t0). Gộp về bản
     ghi có snap_time MUỘN NHẤT cho mỗi (symbol, signal_date) → mỗi lệnh đếm 1 lần.
  4) "Chưa hit gì trong cửa sổ" (neither TP nor SL) → xếp NO_HIT, KHÔNG tính là
     thắng/thua. (Trọng tài có gán WIN_OPEN/LOSS_OPEN theo close — ta BỎ QUA nhãn
     đó để đúng tinh thần "chỉ tính hit TP/SL".)
  5) "Lệnh chưa khớp" (filled=False, giá không hồi về entry) → xếp UNFILLED riêng.

CHẠY:
  python scripts/diag_buy_tpsl_forward.py
  # hoặc chỉ 1 track / lọc regime:
  python scripts/diag_buy_tpsl_forward.py --track v4 --min-mature 30

ĐỌC: chỉ đọc output/history/... — KHÔNG ghi gì, KHÔNG gọi mạng. An toàn tuyệt đối.
"""
import os
import sys
import json
import glob
import argparse
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from config import OUTPUT_DIR
except Exception:
    OUTPUT_DIR = "output"

TRACKS = {
    "v4":   "history/v2f_outcomes_v4",
    "v2.3": "history/v2f_outcomes",
}


def _read_jsonl_dir(subdir):
    rows = []
    for path in sorted(glob.glob(os.path.join(OUTPUT_DIR, subdir, "*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    return rows


def _dedup_daily_last(rows):
    """Giữ bản ghi snap_time muộn nhất cho mỗi (symbol, signal_date)."""
    best = {}
    for r in rows:
        key = (r.get("symbol"), r.get("signal_date"))
        if None in key:
            continue
        cur = best.get(key)
        if cur is None or str(r.get("snap_time") or "") > str(cur.get("snap_time") or ""):
            best[key] = r
    return list(best.values())


def _classify(o):
    """
    Phân loại 1 outcome BUY đã dedup thành:
      TP1 | STOP | NO_HIT | UNFILLED | NO_LEVELS
    Chỉ dựa hit_tp1/hit_sl/filled — KHÔNG dùng close.
    """
    # Không có field 'filled' => trọng tài chưa từng vào nhánh TP/SL
    # (thường vì entry/stop/tp1 = None ở thời điểm ghi pred → LỖI LEVELS).
    if "filled" not in o:
        return "NO_LEVELS"
    if not o.get("filled"):
        return "UNFILLED"
    if o.get("hit_sl"):
        return "STOP"
    if o.get("hit_tp1"):
        return "TP1"
    return "NO_HIT"


def _fmt_pct(n, d):
    return f"{(100.0*n/d):.1f}%" if d else "—"


def run(track_key, min_mature, group_by):
    subdir = TRACKS[track_key]
    rows = _read_jsonl_dir(subdir)
    # chỉ lăng kính trade + chỉ BUY
    rows = [r for r in rows
            if r.get("lens") == "trade"
            and r.get("decision") in ("BUY", "STRONG BUY")]

    print("=" * 66)
    print(f"  BUY FORWARD TP/SL — track {track_key}  ({subdir})")
    print("=" * 66)
    if not rows:
        print("  (không có outcome BUY nào — ledger trống hoặc chưa chín)")
        return

    n_raw = len(rows)
    rows = _dedup_daily_last(rows)
    print(f"  BUY outcome thô: {n_raw}  →  sau dedup daily-last: {len(rows)}")

    buckets = defaultdict(lambda: Counter())
    R_by_grp = defaultdict(list)
    for o in rows:
        cls = _classify(o)
        gkey = "ALL"
        if group_by == "regime":
            gkey = o.get("regime") or o.get("regime_raw") or "?"
        elif group_by == "version":
            gkey = o.get("scoring_version_effective") or o.get("scoring_version") or "?"
        buckets["ALL"][cls] += 1
        if gkey != "ALL":
            buckets[gkey][cls] += 1
        if cls in ("TP1", "STOP"):
            r = o.get("realized_R")
            if isinstance(r, (int, float)):
                R_by_grp["ALL"].append(r)
                if gkey != "ALL":
                    R_by_grp[gkey].append(r)

    order = ["ALL"] + sorted(k for k in buckets if k != "ALL")
    print()
    hdr = f"  {'nhóm':<10} {'TP1':>4} {'STOP':>5} {'NO_HIT':>7} {'UNFIL':>6} {'NOLVL':>6} | {'hit%':>6} {'expR':>7} {'n_res':>6}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for g in order:
        b = buckets[g]
        tp, sl = b["TP1"], b["STOP"]
        res = tp + sl                      # resolved = đã hit TP hoặc SL
        hit = _fmt_pct(tp, res)
        Rs = R_by_grp.get(g, [])
        expR = f"{(sum(Rs)/len(Rs)):+.2f}" if Rs else "—"
        print(f"  {g:<10} {tp:>4} {sl:>5} {b['NO_HIT']:>7} {b['UNFILLED']:>6} "
              f"{b['NO_LEVELS']:>6} | {hit:>6} {expR:>7} {res:>6}")

    all_b = buckets["ALL"]
    res_all = all_b["TP1"] + all_b["STOP"]
    print()
    if all_b["NO_LEVELS"] and not res_all:
        print("  ⚠️ TẤT CẢ lệnh BUY thiếu levels (NO_LEVELS) → trọng tài CHƯA từng")
        print("     chấm TP/SL. Nguyên nhân: entry/stop/tp1=None lúc ghi pred.")
        print("     → Cần fix record_predictions_v4 (trỏ v2f_trade_levels_v4.json),")
        print("       chờ ~cửa-sổ phiên để pred mới chín rồi chạy lại diag này.")
    elif res_all < min_mature:
        print(f"  ⚠️ Mới {res_all} lệnh đã hit TP/SL (< {min_mature}) — CHƯA đủ mẫu.")
        print("     Đọc số là tham khảo; hoãn kết luận tới khi ≥ ngưỡng.")
    else:
        exp = sum(R_by_grp["ALL"]) / len(R_by_grp["ALL"])
        tp_Rs = [r for r in R_by_grp["ALL"] if r > 0]
        tp_avg = (sum(tp_Rs) / len(tp_Rs)) if tp_Rs else 0.0
        verdict = "DƯƠNG (BUY có lãi kỳ vọng)" if exp > 0 else "ÂM (BUY lỗ kỳ vọng)"
        print(f"  Kỳ vọng mỗi lệnh: {exp:+.2f}R trên {res_all} lệnh resolved → {verdict}")
        print(f"  (1R = rủi ro entry→stop. Lệnh TP1 lãi TB +{tp_avg:.2f}R; "
              f"lệnh STOP = -1R. So mốc chi phí vòng 0.30–0.50%.)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", choices=list(TRACKS), default="v4")
    ap.add_argument("--min-mature", type=int, default=30,
                    help="Số lệnh resolved tối thiểu trước khi cho kết luận")
    ap.add_argument("--group-by", choices=["none", "regime", "version"],
                    default="none")
    args = ap.parse_args()
    run(args.track, args.min_mature, args.group_by)


if __name__ == "__main__":
    main()
