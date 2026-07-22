# =============================================================================
# scripts/diag_rank_backtest.py — Trọng tài cho hướng "xếp hạng trong nhóm"
# =============================================================================
# Chạy qua debug.yml. CHỈ ĐỌC. Trả lời câu hỏi: xếp hạng trong 6 nhóm ngành
# có phân tầng thắng/thua tốt hơn điểm tuyệt đối hiện tại không?
#
# HAI CHẾ ĐỘ trong cùng một lần chạy:
#   [RETRO]   Phiếu cũ (chưa có trường rank_*): tự tính lại rank hồi tố từ
#             điểm thành phần trong sổ → có kết quả NGAY trên ~4 tuần đã chấm.
#             Giới hạn: rank cơ bản hồi tố dùng fundamental_score (không có
#             raw PE/PB trong sổ cũ) — xấp xỉ, ghi rõ.
#   [FORWARD] Phiếu mới (có trường rank_* ghi thầm từ 22/07): dùng thẳng số
#             đã ghi tại thời điểm phát — chuẩn nhất, không look-ahead.
#
# TIÊU CHÍ CHỐT (đăng ký trước, tránh dời cột mốc):
#   Promote xếp-hạng-nhóm vào công thức chính thức (bump SCORING_VERSION) khi:
#   (C1) FORWARD ≥ 2 tuần outcomes, ≥ 250 phiếu daily-last có rank fields
#   (C2) rank_fund_grp: top30% − bot30% ≥ +0.5%/10 phiên, cùng dấu với RETRO
#   (C3) rank_trend_grp: gap ≥ +0.5%/10 phiên, hit top ≥ 55%
#   (C4) Không nhóm ngành nào (≥30 phiếu) bị đảo dấu nặng (gap ≤ −1%)
#   Không đạt → giữ nguyên v2.3, tiếp tục tích lũy.
# =============================================================================
import json
import glob
import statistics as st
from collections import defaultdict

DIRTY_EVAL = {"2026-07-20", "2026-07-22"}   # lượt chấm giữa phiên (nến dở)
CA_WINDOWS = [
    ("OCB", "2026-06-24", "2026-06-29"), ("CTR", "2026-06-25", "2026-07-08"),
    ("PVD", "2026-06-30", "2026-07-13"), ("VCG", "2026-06-30", "2026-07-13"),
    ("VTP", "2026-06-30", "2026-07-13"),
]
GROUPS = {
    "Ngân hàng": "NGAN_HANG", "Bất động sản": "BAT_DONG_SAN",
    "Dịch vụ tài chính": "TAI_CHINH_PHI_NH", "Bảo hiểm": "TAI_CHINH_PHI_NH",
    "Xây dựng và Vật liệu": "CONG_NGHIEP",
    "Hàng & Dịch vụ Công nghiệp": "CONG_NGHIEP",
    "Tài nguyên Cơ bản": "NGUYEN_LIEU_NANG_LUONG",
    "Hóa chất": "NGUYEN_LIEU_NANG_LUONG", "Dầu khí": "NGUYEN_LIEU_NANG_LUONG",
    "Điện, nước & xăng dầu khí đốt": "NGUYEN_LIEU_NANG_LUONG",
    "Thực phẩm và đồ uống": "TIEU_DUNG_DICH_VU", "Bán lẻ": "TIEU_DUNG_DICH_VU",
    "Y tế": "TIEU_DUNG_DICH_VU", "Du lịch và Giải trí": "TIEU_DUNG_DICH_VU",
    "Hàng cá nhân & Gia dụng": "TIEU_DUNG_DICH_VU",
    "Ô tô và phụ tùng": "TIEU_DUNG_DICH_VU",
    "Công nghệ Thông tin": "TIEU_DUNG_DICH_VU",
    "Truyền thông": "TIEU_DUNG_DICH_VU", "Viễn thông": "TIEU_DUNG_DICH_VU",
}


def load_jsonl(pattern):
    out = []
    for f in sorted(glob.glob(pattern)):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
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
    return any(sym == s and a <= d <= b for s, a, b in CA_WINDOWS)


def num(x):
    return x if isinstance(x, (int, float)) else None


def pct_rank(sorted_vals, v):
    n = len(sorted_vals)
    if n < 3:
        return None
    below = sum(1 for x in sorted_vals if x < v)
    equal = sum(1 for x in sorted_vals if x == v)
    return (below + 0.5 * equal) / n


def retro_ranks(preds):
    """Tính rank hồi tố trong (ngày, nhóm) từ điểm thành phần trong sổ."""
    by = defaultdict(list)
    for p in preds:
        p["_grp"] = p.get("sector_group") or GROUPS.get(p.get("industry"), "KHAC")
        by[(p["signal_date"], p["_grp"])].append(p)
    for _, rs in by.items():
        for fld, out in (("fundamental_score", "_r_fund"),
                         ("trend_score", "_r_trend")):
            vals = sorted(num(x.get(fld)) for x in rs
                          if num(x.get(fld)) is not None)
            for x in rs:
                v = num(x.get(fld))
                x[out] = pct_rank(vals, v) if v is not None else None


def spread_report(recs, rank_field, label, uni):
    top = [r for r in recs if (r.get(rank_field) or -1) >= 0.70]
    bot = [r for r in recs if r.get(rank_field) is not None
           and r[rank_field] <= 0.30]
    out = [f"  {label}:"]
    gaps = {}
    for h in ("ret_5d", "ret_10d"):
        res = {}
        for nm, grp in (("top", top), ("bot", bot)):
            xs = [r[h] - uni[(r["signal_date"], h)] for r in grp
                  if num(r.get(h)) is not None
                  and (r["signal_date"], h) in uni
                  and not (h == "ret_10d" and r.get("_dirty10"))]
            if len(xs) >= 15:
                res[nm] = (st.mean(xs),
                           100 * sum(1 for x in xs if x > 0) / len(xs), len(xs))
        if "top" in res and "bot" in res:
            t, b = res["top"], res["bot"]
            gaps[h] = t[0] - b[0]
            out.append(f"    {h[4:]:>3}: top30 {t[0]:+.2f}% ({t[1]:.0f}%, n={t[2]})"
                       f" | bot30 {b[0]:+.2f}% ({b[1]:.0f}%, n={b[2]})"
                       f" | GAP {t[0]-b[0]:+.2f}%")
        else:
            out.append(f"    {h[4:]:>3}: chưa đủ mẫu (top={len(top)}, bot={len(bot)})")
    print("\n".join(out))
    return gaps


def main():
    print("=" * 74)
    print("DIAG RANK BACKTEST — xếp hạng trong 6 nhóm ngành vs điểm tuyệt đối")
    print("=" * 74)

    preds = daily_last(load_jsonl("output/history/v2f_predictions/*.jsonl"))
    outs = daily_last(load_jsonl("output/history/v2f_outcomes/*.jsonl"))
    outs = [o for o in outs if not is_ca(o.get("symbol", ""),
                                         o.get("signal_date", ""))]
    for o in outs:
        o["_dirty10"] = (o.get("n_bars") == 10
                         and o.get("eval_date") in DIRTY_EVAL)

    pmap = {(p["symbol"], p["signal_date"]): p for p in preds}
    joined = []
    for o in outs:
        p = pmap.get((o["symbol"], o["signal_date"]))
        if p:
            o["_p"] = p
            joined.append(o)
    print(f"Join outcomes↔ledger: {len(joined)} phiếu daily-last "
          f"(đã loại CA; 10d loại nến dở)")

    # rank hồi tố cho mọi phiếu; phiếu forward dùng trường ghi thầm nếu có
    retro_ranks([o["_p"] for o in joined])
    n_fwd = 0
    for o in joined:
        p = o["_p"]
        if p.get("rank_fund_grp") is not None:      # FORWARD (ghi thầm)
            o["_rf"], o["_rt"], o["_mode"] = (p["rank_fund_grp"],
                                              p.get("rank_trend_grp"), "FWD")
            n_fwd += 1
        else:                                        # RETRO (xấp xỉ)
            o["_rf"], o["_rt"], o["_mode"] = (p.get("_r_fund"),
                                              p.get("_r_trend"), "RETRO")
        o["_grp"] = p.get("_grp")

    uni = {}
    byd = defaultdict(list)
    for o in joined:
        byd[o["signal_date"]].append(o)
    for d, rs in byd.items():
        for h in ("ret_5d", "ret_10d"):
            xs = [num(r.get(h)) for r in rs]
            xs = [x for x in xs if x is not None]
            if xs:
                uni[(d, h)] = st.mean(xs)

    retro = [o for o in joined if o["_mode"] == "RETRO"]
    fwd = [o for o in joined if o["_mode"] == "FWD"]
    print(f"Phiếu RETRO: {len(retro)} | Phiếu FORWARD (có rank ghi thầm): {len(fwd)}")

    print("\n[RETRO] — rank hồi tố từ điểm thành phần (xấp xỉ)")
    g1 = spread_report(retro, "_rf", "Cơ bản (rank nhóm)", uni)
    g2 = spread_report(retro, "_rt", "Xu hướng (rank nhóm)", uni)

    if fwd:
        print("\n[FORWARD] — rank ghi thầm tại thời điểm phát (chuẩn)")
        f1 = spread_report(fwd, "_rf", "Cơ bản (rank_fund_grp)", uni)
        f2 = spread_report(fwd, "_rt", "Xu hướng (rank_trend_grp)", uni)

        print("\n[C4] Kiểm tra đảo dấu theo nhóm (FORWARD, gap 10d):")
        for grp in sorted({o["_grp"] for o in fwd}):
            sub = [o for o in fwd if o["_grp"] == grp]
            if len(sub) < 30:
                continue
            gg = spread_report(sub, "_rf", f"  {grp}", uni)

        print("\n===== ĐỐI CHIẾU TIÊU CHÍ CHỐT (đăng ký trước) =====")
        ok1 = len(fwd) >= 250
        ok2 = (f1.get("ret_10d") or -9) >= 0.5 and \
              (g1.get("ret_10d") or 0) * (f1.get("ret_10d") or 0) > 0
        ok3 = (f2.get("ret_10d") or -9) >= 0.5
        print(f"  C1 n_forward>=250      : {'ĐẠT' if ok1 else 'CHƯA'} ({len(fwd)})")
        print(f"  C2 fund gap>=+0.5%/10d : {'ĐẠT' if ok2 else 'CHƯA'} "
              f"(fwd={f1.get('ret_10d')}, retro={g1.get('ret_10d')})")
        print(f"  C3 trend gap>=+0.5%/10d: {'ĐẠT' if ok3 else 'CHƯA'} "
              f"(fwd={f2.get('ret_10d')})")
        print("  C4: xem bảng nhóm phía trên (không nhóm nào gap<=-1%)")
        if ok1 and ok2 and ok3:
            print("  → ĐỦ ĐIỀU KIỆN đề xuất promote (bump SCORING_VERSION tại round-1)")
        else:
            print("  → GIỮ v2.3, tiếp tục tích lũy")
    else:
        print("\n[FORWARD] chưa có phiếu nào mang trường rank ghi thầm "
              "(deploy scoring+recorder trước, chờ outcomes chín)")

    print("\nLƯU Ý: script chỉ theo dõi; KHÔNG tự sửa scoring. RETRO dùng "
          "fundamental_score làm xấp xỉ (sổ cũ không có raw PE/PB) — kết luận "
          "cuối dựa trên FORWARD.")


if __name__ == "__main__":
    main()
