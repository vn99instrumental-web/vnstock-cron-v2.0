"""
utils/v2f_industry_groups.py — Phân 6 nhóm ngành + xếp hạng trong nhóm (GHI THẦM)
==================================================================================
Sinh ra từ phân tích 22/07/2026: điểm cơ bản chấm ngưỡng TUYỆT ĐỐI đang đo
"đây là ngành nào" thay vì "doanh nghiệp này tốt hơn đồng nghiệp không"
(Ngân hàng auto +10 vì PE cấu trúc 7.6; BĐS auto bị trừ vì PE cấu trúc 15.5).
Kiểm định trên 1.123 outcomes: xếp hạng TRONG NHÓM phân tầng +1.12%/10 phiên
(cơ bản), +1.63% (xu hướng); ngưỡng tuyệt đối gần 0.

GIAI ĐOẠN HIỆN TẠI: GHI THẦM (shadow write). Module này CHỈ tính và gắn thêm
trường vào signal rows để ghi vào sổ dự đoán — KHÔNG thay đổi bất kỳ điểm số,
decision hay SCORING_VERSION nào. Quyết định promote sang công thức chính thức
sẽ dựa trên đối chiếu forward (xem scripts/diag_rank_backtest.py).

THIẾT KẾ MECE (audit 22/07):
  - ME: industry_map 3.513 symbol duy nhất, 0 đa ngành; bảng map 1 ngành con
        → đúng 1 nhóm; nhóm chốt tại thời điểm phát tín hiệu, ghi vào phiếu.
  - CE: 19 ngành con có tên được phủ; icb_name rỗng/lạ → nhóm "KHAC"
        (xếp hạng 100% toàn rổ) + log warning. Mọi input đều có đường ra.

XỬ LÝ QUY MÔ (không chia nhóm theo size — ma trận 6x3 cho ô 1-3 mã, chết):
  1. rank_fund_grp dùng CẶP chỉ số tự trung hòa premium thanh khoản:
     rẻ-PE + rẻ-PB (mã lớn thua) đối trọng cao-ROE + thấp-D/E (mã lớn thắng).
  2. Ngành con nằm nhờ nhóm khác cấu trúc (CNTT, Bảo hiểm, Truyền thông,
     Viễn thông) → hạng pha trộn 50/50 (nhóm / toàn rổ).
  3. adtv_bil + size_band ghi kèm để kiểm định theo cỡ + làm nguyên liệu
     cổng ADTV sau này.
"""
from __future__ import annotations

import logging

log = logging.getLogger("v2f_industry_groups")

# ── Bảng ngành con (icb_name cấp 2) → 6 nhóm cấu trúc định giá ──
# Căn cứ PE/PB trung vị thực tế (finance cache 07/2026) — xem changelog dự án.
SUBSECTOR_TO_GROUP = {
    "Ngân hàng":                        "NGAN_HANG",
    "Bất động sản":                     "BAT_DONG_SAN",
    "Dịch vụ tài chính":                "TAI_CHINH_PHI_NH",
    "Bảo hiểm":                         "TAI_CHINH_PHI_NH",
    "Xây dựng và Vật liệu":             "CONG_NGHIEP",
    "Hàng & Dịch vụ Công nghiệp":       "CONG_NGHIEP",
    "Tài nguyên Cơ bản":                "NGUYEN_LIEU_NANG_LUONG",
    "Hóa chất":                         "NGUYEN_LIEU_NANG_LUONG",
    "Dầu khí":                          "NGUYEN_LIEU_NANG_LUONG",
    "Điện, nước & xăng dầu khí đốt":    "NGUYEN_LIEU_NANG_LUONG",
    "Thực phẩm và đồ uống":             "TIEU_DUNG_DICH_VU",
    "Bán lẻ":                           "TIEU_DUNG_DICH_VU",
    "Y tế":                             "TIEU_DUNG_DICH_VU",
    "Du lịch và Giải trí":              "TIEU_DUNG_DICH_VU",
    "Hàng cá nhân & Gia dụng":          "TIEU_DUNG_DICH_VU",
    "Ô tô và phụ tùng":                 "TIEU_DUNG_DICH_VU",
    "Công nghệ Thông tin":              "TIEU_DUNG_DICH_VU",
    # CE vá 22/07: 2 ngành chưa xuất hiện trong universe nhưng tồn tại trên
    # thị trường (đảo rổ VN100 / mở UPCOM có thể mang vào):
    "Truyền thông":                     "TIEU_DUNG_DICH_VU",
    "Viễn thông":                       "TIEU_DUNG_DICH_VU",
}

FALLBACK_GROUP = "KHAC"   # icb_name rỗng / lạ → xếp hạng 100% toàn rổ

# Ngành con nhỏ nằm nhờ nhóm khác cấu trúc định giá → hạng pha trộn 50/50
BLEND_SUBSECTORS = {
    "Công nghệ Thông tin", "Bảo hiểm", "Truyền thông", "Viễn thông",
}

# Ngưỡng size_band theo GTGD/ngày (đồng) — tam phân vị universe 07/2026;
# cố định để size_band ổn định giữa các phiên (không trôi theo ngày).
SIZE_LARGE_VND = 71e9
SIZE_MID_VND   = 15e9


def get_group(industry: str | None) -> str:
    """Ngành con → nhóm. MECE: mọi input (kể cả None/rỗng/lạ) có đúng 1 nhóm."""
    if not industry:
        return FALLBACK_GROUP
    g = SUBSECTOR_TO_GROUP.get(str(industry).strip())
    if g is None:
        log.warning(f"[industry_groups] icb_name lạ chưa có trong bảng: "
                    f"'{industry}' → nhóm {FALLBACK_GROUP} (cần cập nhật bảng)")
        return FALLBACK_GROUP
    return g


def _f(v):
    try:
        f = float(v)
        return f if f == f else None   # loại NaN
    except (TypeError, ValueError):
        return None


def _pct_rank(sorted_vals: list, v: float) -> float:
    """Vị trí phần trăm của v trong sorted_vals ∈ [0,1] (0.5 nếu nhóm rỗng)."""
    n = len(sorted_vals)
    if n == 0:
        return 0.5
    below = 0
    equal = 0
    for x in sorted_vals:
        if x < v:
            below += 1
        elif x == v:
            equal += 1
        else:
            break
    return (below + 0.5 * equal) / n


def _rank_in(pool_vals: list, v, higher_is_better: bool = True):
    """Hạng của v trong pool (đã lọc None). None nếu v hoặc pool không dùng được."""
    v = _f(v)
    vals = sorted(x for x in (map(_f, pool_vals)) if x is not None)
    if v is None or len(vals) < 3:     # nhóm < 3 giá trị → hạng vô nghĩa
        return None
    r = _pct_rank(vals, v)
    return round(r if higher_is_better else 1.0 - r, 4)


def _fund_components(row: dict) -> dict:
    """Trích 4 thành phần cơ bản; PE/PB chỉ nhận giá trị dương (âm = lỗ/âm VCSH,
    xử lý riêng bằng cách xếp đáy)."""
    pe = _f(row.get("r_pe"))
    pb = _f(row.get("r_pb"))
    return {
        "pe":  pe if (pe is not None and pe > 0) else None,
        "pb":  pb if (pb is not None and pb > 0) else None,
        "roe": _f(row.get("r_roe")),
        "de":  _f(row.get("bs_debt_to_equity")),
    }


def size_band(accumulated_value) -> str | None:
    v = _f(accumulated_value)
    if v is None or v <= 0:
        return None
    if v >= SIZE_LARGE_VND:
        return "LON"
    if v >= SIZE_MID_VND:
        return "VUA"
    return "NHO"


def compute_group_ranks(rows: list) -> None:
    """
    GHI THẦM: gắn vào MỖI row các trường sau (không sửa trường nào có sẵn):
      sector_group      : 1 trong 6 nhóm hoặc KHAC (chốt tại thời điểm chấm)
      rank_fund_grp     : hạng cơ bản trong nhóm ∈ [0,1] — trung bình của
                          [rẻ-PE, rẻ-PB, cao-ROE, thấp-D/E] (thành phần thiếu
                          thì bỏ qua; PE/PB âm xếp hạng 0.0 vế đó)
      rank_trend_grp    : hạng trend_score trong nhóm
      rank_ff_grp       : hạng ff_score trong nhóm (theo dõi — FF chưa chứng
                          minh giá trị, KHÔNG dùng ra quyết định)
      rank_cf_grp       : hạng cf_score trong nhóm
      rank_growth_grp   : hạng growth_score trong nhóm
      rank_fund_uni     : hạng cơ bản toàn rổ (phục vụ blend + đối chiếu)
      adtv_bil          : GTGD phiên (tỷ đồng, từ accumulated_value)
      size_band         : LON / VUA / NHO / None
    Ngành con thuộc BLEND_SUBSECTORS: rank_*_grp = 0.5*nhóm + 0.5*toàn rổ.
    Nhóm KHAC: rank_*_grp = hạng toàn rổ.
    """
    if not rows:
        return

    for r in rows:
        r["sector_group"] = get_group(r.get("industry"))

    # Gom pool theo nhóm + pool toàn rổ
    groups: dict = {}
    for r in rows:
        groups.setdefault(r["sector_group"], []).append(r)
    universe = rows

    def fund_rank(row: dict, pool: list):
        """Hạng cơ bản composite của row trong pool."""
        comp = _fund_components(row)
        pool_comp = [_fund_components(x) for x in pool]
        parts = []
        # rẻ-PE (thấp tốt); PE âm → 0.0 (đáy)
        pe_raw = _f(row.get("r_pe"))
        if comp["pe"] is not None:
            rk = _rank_in([c["pe"] for c in pool_comp], comp["pe"],
                          higher_is_better=False)
            if rk is not None:
                parts.append(rk)
        elif pe_raw is not None and pe_raw < 0:
            parts.append(0.0)
        # rẻ-PB (thấp tốt); PB âm → 0.0
        pb_raw = _f(row.get("r_pb"))
        if comp["pb"] is not None:
            rk = _rank_in([c["pb"] for c in pool_comp], comp["pb"],
                          higher_is_better=False)
            if rk is not None:
                parts.append(rk)
        elif pb_raw is not None and pb_raw < 0:
            parts.append(0.0)
        # cao-ROE
        if comp["roe"] is not None:
            rk = _rank_in([c["roe"] for c in pool_comp], comp["roe"],
                          higher_is_better=True)
            if rk is not None:
                parts.append(rk)
        # thấp-D/E (None phổ biến ở ngân hàng — đơn giản bỏ qua vế này)
        if comp["de"] is not None:
            rk = _rank_in([c["de"] for c in pool_comp], comp["de"],
                          higher_is_better=False)
            if rk is not None:
                parts.append(rk)
        return round(sum(parts) / len(parts), 4) if parts else None

    def score_rank(row: dict, pool: list, field: str):
        return _rank_in([x.get(field) for x in pool], row.get(field),
                        higher_is_better=True)

    def blend(a, b):
        if a is None:
            return b
        if b is None:
            return a
        return round(0.5 * a + 0.5 * b, 4)

    n_khac = 0
    for r in rows:
        grp  = r["sector_group"]
        pool = groups[grp]
        use_blend = (str(r.get("industry") or "").strip() in BLEND_SUBSECTORS)

        f_grp = fund_rank(r, pool)
        f_uni = fund_rank(r, universe)
        r["rank_fund_uni"] = f_uni

        if grp == FALLBACK_GROUP:
            n_khac += 1
            r["rank_fund_grp"]   = f_uni
            r["rank_trend_grp"]  = score_rank(r, universe, "trend_score")
            r["rank_ff_grp"]     = score_rank(r, universe, "ff_score")
            r["rank_cf_grp"]     = score_rank(r, universe, "cf_score")
            r["rank_growth_grp"] = score_rank(r, universe, "growth_score")
        elif use_blend:
            r["rank_fund_grp"]   = blend(f_grp, f_uni)
            r["rank_trend_grp"]  = blend(score_rank(r, pool, "trend_score"),
                                         score_rank(r, universe, "trend_score"))
            r["rank_ff_grp"]     = blend(score_rank(r, pool, "ff_score"),
                                         score_rank(r, universe, "ff_score"))
            r["rank_cf_grp"]     = blend(score_rank(r, pool, "cf_score"),
                                         score_rank(r, universe, "cf_score"))
            r["rank_growth_grp"] = blend(score_rank(r, pool, "growth_score"),
                                         score_rank(r, universe, "growth_score"))
        else:
            r["rank_fund_grp"]   = f_grp
            r["rank_trend_grp"]  = score_rank(r, pool, "trend_score")
            r["rank_ff_grp"]     = score_rank(r, pool, "ff_score")
            r["rank_cf_grp"]     = score_rank(r, pool, "cf_score")
            r["rank_growth_grp"] = score_rank(r, pool, "growth_score")

        av = _f(r.get("accumulated_value"))
        r["adtv_bil"]  = round(av / 1e9, 2) if av else None
        r["size_band"] = size_band(av)

    sizes = {g: len(v) for g, v in groups.items()}
    log.info(f"[industry_groups] nhóm: {sizes}"
             + (f" | CẢNH BÁO {n_khac} mã rơi nhóm KHAC" if n_khac else ""))
