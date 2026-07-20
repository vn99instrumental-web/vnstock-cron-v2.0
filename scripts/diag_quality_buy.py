# =============================================================================
# scripts/diag_quality_buy.py — Trọng tài riêng cho giả thuyết QUALITY_BUY
# =============================================================================
# Chạy qua debug.yml (manual). CHỈ ĐỌC, không ghi file, không sửa scoring.
# Stdlib only. Đọc ledger + outcomes cả 2 sổ, xuất báo cáo:
#   [1] Sổ A: QUALITY_BUY (ff>=5 & fund>=5) vs BUY thường — ret lens + order lens
#   [2] Sổ B: BUY tách theo overlay A-quality (đúng semantic tag dashboard v3)
#   [3] Sổ B: dò ngưỡng native s_ff_net / s_fund_core
#   [4] Sổ A: mô phỏng gate (BUY không đạt QUALITY -> NEUTRAL)
# Quy tắc dữ liệu:
#   - daily-last: 1 phiếu/mã/ngày (snap muộn nhất)
#   - excess = ret - trung bình toàn rổ cùng ngày cùng kỳ hạn (cùng sổ)
#   - ret_* KHÔNG cần lọc điều chỉnh giá (VCI adjusted 2 đầu — đã kiểm chứng OCB)
#   - realized_R PHẢI lọc cửa sổ điều chỉnh giá (stop giả do entry/SL giá thô)
# =============================================================================
import json
import glob
import statistics as st
from collections import defaultdict

# Cửa sổ điều chỉnh giá kỹ thuật (chia cổ tức/tách) — chỉ áp cho ORDER LENS
CA_WINDOWS = [
    ("OCB", "2026-06-24", "2026-06-29"),
    ("CTR", "2026-06-25", "2026-07-08"),
    ("PVD", "2026-06-30", "2026-07-13"),
    ("VCG", "2026-06-30", "2026-07-13"),
    ("VTP", "2026-06-30", "2026-07-13"),
]

QB_FF = 5.0    # ngưỡng QUALITY đã kiểm chứng (thang v2.3)
QB_FUND = 5.0
HORIZONS = ("ret_3d", "ret_5d", "ret_10d")


def load_jsonl(pattern):
    out = []
    for f in sorted(glob.glob(pattern)):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def daily_last(rows):
    best = {}
    for r in rows:
        k = (r.get("symbol"), r.get("signal_date"))
        if None in k:
            continue
        cur = best.get(k)
        if cur is None or (r.get("snap_time") or "") > (cur.get("snap_time") or ""):
            best[k] = r
    return list(best.values())


def is_ca(sym, d):
    for s, a, b in CA_WINDOWS:
        if sym == s and a <= d <= b:
            return True
    return False


def num(x):
    return x if isinstance(x, (int, float)) else None


def universe_means(rows):
    uni = {}
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["signal_date"]].append(r)
    for d, rs in by_day.items():
        for k in HORIZONS:
            xs = [num(r.get(k)) for r in rs]
            xs = [x for x in xs if x is not None]
            if xs:
                uni[(d, k)] = st.mean(xs)
    return uni


def excess_stats(rows, uni):
    parts = []
    for k in HORIZONS:
        xs = []
        for r in rows:
            v = num(r.get(k))
            key = (r["signal_date"], k)
            if v is not None and key in uni:
                xs.append(v - uni[key])
        if xs:
            hit = 100.0 * sum(1 for x in xs if x > 0) / len(xs)
            parts.append("exc%s=%+.2f%% hit=%.0f%% n=%d"
                         % (k[4:], st.mean(xs), hit, len(xs)))
        else:
            parts.append("exc%s=-" % k[4:])
    return " | ".join(parts)


def order_stats(rows):
    Rs = [num(r.get("realized_R")) for r in rows
          if not is_ca(r.get("symbol", ""), r.get("signal_date", ""))]
    Rs = [x for x in Rs if x is not None]
    n_ca = sum(1 for r in rows
               if num(r.get("realized_R")) is not None
               and is_ca(r.get("symbol", ""), r.get("signal_date", "")))
    if not Rs:
        return "khong co lenh (sau loc CA: bo %d phieu)" % n_ca
    win = sum(1 for x in Rs if x > 0)
    stop = sum(1 for x in Rs if x <= -0.99)
    return ("n=%d E[R]=%+.3f win=%d stop=%d (da loc %d phieu CA)"
            % (len(Rs), st.mean(Rs), win, stop, n_ca))


def main():
    print("=" * 72)
    print("DIAG QUALITY_BUY — rule: ff_score>=%.0f & fundamental_score>=%.0f (thang v2.3)"
          % (QB_FF, QB_FUND))
    print("=" * 72)

    led_a = daily_last(load_jsonl("output/history/v2f_predictions/*.jsonl"))
    led_b = daily_last(load_jsonl("output/history/v2f_predictions_v3/*.jsonl"))
    out_a = daily_last(load_jsonl("output/history/v2f_outcomes/*.jsonl"))
    out_b = daily_last(load_jsonl("output/history/v2f_outcomes_v3/*.jsonl"))
    print("Daily-last: ledgerA=%d ledgerB=%d | outcomesA=%d outcomesB=%d"
          % (len(led_a), len(led_b), len(out_a), len(out_b)))

    # map (sym, date) -> (ff, fund) tu ledger A; pred_id -> (ff, fund) du phong
    a_meta_sd = {}
    a_meta_pid = {}
    for r in led_a:
        ff = num(r.get("ff_score")) or 0.0
        fu = num(r.get("fundamental_score")) or 0.0
        a_meta_sd[(r["symbol"], r["signal_date"])] = (ff, fu)
        if r.get("pred_id"):
            a_meta_pid[r["pred_id"]] = (ff, fu)

    def a_quality(rec):
        m = a_meta_pid.get(rec.get("pred_id")) or \
            a_meta_sd.get((rec.get("symbol"), rec.get("signal_date")))
        if m is None:
            return None
        return m[0] >= QB_FF and m[1] >= QB_FUND

    uni_a = universe_means(out_a)
    uni_b = universe_means(out_b)

    # ---------- [1] So A ----------
    print("\n[1] SO A (v2.3): QUALITY_BUY vs BUY thuong")
    buys_a = [r for r in out_a if r.get("decision") in ("BUY", "STRONG BUY")]
    q, n, unk = [], [], 0
    for r in buys_a:
        v = a_quality(r)
        if v is None:
            unk += 1
        elif v:
            q.append(r)
        else:
            n.append(r)
    print("  BUY daily-last: %d (QUALITY=%d, thuong=%d, khong join duoc=%d)"
          % (len(buys_a), len(q), len(n), unk))
    print("  QUALITY : " + excess_stats(q, uni_a))
    print("            order lens: " + order_stats(q))
    print("  Thuong  : " + excess_stats(n, uni_a))
    print("            order lens: " + order_stats(n))

    # ---------- [2] So B overlay ----------
    print("\n[2] SO B (v3): BUY tach theo overlay A-quality (semantic tag dashboard)")
    buys_b = [r for r in out_b if r.get("decision") in ("BUY", "STRONG BUY")]
    bq, bn, bunk = [], [], 0
    for r in buys_b:
        m = a_meta_sd.get((r.get("symbol"), r.get("signal_date")))
        if m is None:
            bunk += 1
        elif m[0] >= QB_FF and m[1] >= QB_FUND:
            bq.append(r)
        else:
            bn.append(r)
    print("  v3 BUY daily-last: %d (A-quality=%d, thuong=%d, khong join=%d)"
          % (len(buys_b), len(bq), len(bn), bunk))
    print("  A-quality: " + excess_stats(bq, uni_b))
    print("             order lens: " + order_stats(bq))
    print("  Thuong   : " + excess_stats(bn, uni_b))
    print("             order lens: " + order_stats(bn))

    # ---------- [3] Do nguong native v3 ----------
    print("\n[3] SO B: do nguong native (s_ff_net / s_fund_core tu ledger B)")
    b_meta = {}
    for r in led_b:
        b_meta[(r["symbol"], r["signal_date"])] = (
            num(r.get("s_ff_net")) or 0.0, num(r.get("s_fund_core")) or 0.0)
    for tff in (2, 3):
        for tfd in (2, 3):
            grp_q, grp_n = [], []
            for r in buys_b:
                m = b_meta.get((r.get("symbol"), r.get("signal_date")))
                if m is None:
                    continue
                (grp_q if (m[0] >= tff and m[1] >= tfd) else grp_n).append(r)
            if len(grp_q) < 3:
                print("  ff>=%d & fund>=%d: n=%d — qua it, bo qua" % (tff, tfd, len(grp_q)))
                continue
            print("  ff>=%d & fund>=%d:" % (tff, tfd))
            print("    Q      : " + excess_stats(grp_q, uni_b))
            print("    thuong : " + excess_stats(grp_n, uni_b))

    # ---------- [4] Gate simulation so A ----------
    print("\n[4] SO A: mo phong gate (BUY khong dat QUALITY -> NEUTRAL) tren ledger")
    dist_now = defaultdict(int)
    dist_gate = defaultdict(int)
    for r in led_a:
        dec = r.get("decision")
        dist_now[dec] += 1
        if dec in ("BUY", "STRONG BUY"):
            v = a_quality(r)
            dist_gate[dec if v else "NEUTRAL"] += 1
        else:
            dist_gate[dec] += 1
    order = ["STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"]
    print("  Hien tai : " + " | ".join("%s=%d" % (k, dist_now.get(k, 0)) for k in order))
    print("  Sau gate : " + " | ".join("%s=%d" % (k, dist_gate.get(k, 0)) for k in order))

    print("\nLUU Y: ket qua chi mang tinh theo doi calibration; KHONG tu dong sua "
          "scoring. Moi thay doi scoring can quyet dinh round 1 + bump version.")


if __name__ == "__main__":
    main()
