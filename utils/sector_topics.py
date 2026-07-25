# utils/sector_topics.py
# ============================================================================
# TỪ KHÓA CHỦ ĐỀ theo nhóm ngành HẸP (bổ trợ cho gắn mã)
# ============================================================================
# MỤC ĐÍCH: bắt tin CHỦ ĐỀ ngành không nhắc đích danh mã.
#   VD "Bộ Công Thương kiểm tra kinh doanh kim cương toàn quốc" → PNJ,
#   dù bài không chứa chữ "PNJ".
#
# CÁCH DÙNG (chốt 24/07/2026 — Cách 1 có hệ số giảm):
#   - Bài chứa từ khóa chủ đề của 1 nhóm hẹp → gán cho TẤT CẢ mã trong nhóm
#     với điểm × TOPIC_DECAY (0.6) vì không đích danh mã.
#   - Nếu bài ĐỒNG THỜI nhắc đích danh 1 mã trong nhóm → mã đó ăn điểm đầy
#     đủ (ticker path), không nhân TOPIC_DECAY. Không cộng chồng.
#   - Chỉ áp cho nhóm HẸP (narrow). Nhóm RỘNG chỉ vào nhiệt độ ngành.
#
# NGUYÊN TẮC VIẾT TỪ KHÓA (chặt để tránh gán nhầm — bài học "vàng"/"đá quý"
# bị nhét nhầm ngành Khai khoáng trong hệ thống cũ):
#   1. ĐẶC HIỆU, không mượn từ chung. "vàng miếng"/"kim cương" ✔ ;
#      "vàng" trần ✘ (dính tỷ giá, giá vàng SJC vĩ mô).
#   2. Ưu tiên CỤM 2-3 CHỮ hơn từ đơn. "cảng biển" ✔ ; "cảng" ✘ (cảng
#      hàng không). "phân bón" ✔ ; "đạm" ✘.
#   3. KHÔNG cụm nào xuất hiện ở >1 nhóm (validate() ép buộc).
#   4. Cụm phải đọc lên là biết NGÀNH NÀO, không cần ngữ cảnh thêm.
#
# NHÓM CỐ Ý ĐỂ TRỐNG (từ vựng quá phổ biến, gán nhầm > gán đúng — chỉ bắt
# qua mã + tên công ty): nuoc(BWE), o_to(HUT), hoa_chat_khac(PLC),
# tai_chinh_khac(EVF), moi_gioi_bds(DXS), bds_cho_thue_ban_le(VRE),
# du_lich_nghi_duong(VPL), dv_hang_hoa_hang_khong(SCS), chuyen_phat(VTP),
# thiet_bi_dien(GEE/GEX), xay_lap_dien_vt(CTR/PC1), lam_san_giay(CAP),
# ban_le_dien_may(MWG), van_tai_dau_khi(PVT).
# → để trống KHÔNG phải thiếu sót: thà không có tín hiệu ngành còn hơn sai.
# ============================================================================

TOPIC_DECAY = 0.6   # tin chủ đề không đích danh mã → điểm × hệ số này

# key = mã nhóm ngành (khớp SECTORS trong sector_map.py)
# value = danh sách cụm từ khóa đặc hiệu (lowercase, match substring)
SECTOR_TOPICS: dict[str, list[str]] = {

    # ── Vàng bạc, trang sức, đá quý (PNJ) ──
    "vang_bac_trang_suc": [
        "kim cương", "trang sức", "vàng miếng", "vàng trang sức",
        "vàng nữ trang", "nữ trang", "đá quý", "kim hoàn",
        "vàng bạc đá quý", "buôn lậu vàng", "buôn lậu kim cương",
        "kinh doanh vàng", "cửa hàng vàng", "tiệm vàng", "chế tác vàng",
    ],

    # ── Thép (HPG, HSG, NKG) ──
    "thep": [
        "giá thép", "ngành thép", "thép xây dựng", "thép cuộn",
        "thép cán nóng", "hrc", "tôn mạ", "ống thép", "phôi thép",
        "quặng sắt", "thép cuộn cán nóng", "chống bán phá giá thép",
        "xuất khẩu thép", "thép không gỉ",
    ],

    # ── Than & khoáng sản (TMB, TVD) ──
    "than_khoang_san": [
        "giá than", "ngành than", "khai thác than", "than antraxit",
        "tkv", "vinacomin", "sản lượng than", "than nhiệt",
    ],

    # ── Dịch vụ & thiết bị dầu khí (PVB, PVC, PVD, PVS) ──
    "dv_dau_khi": [
        "giàn khoan", "dịch vụ dầu khí", "khoan dầu khí", "lô b",
        "cá voi xanh", "thượng nguồn dầu khí", "đường ống dẫn khí",
        "giá thuê giàn khoan", "dự án dầu khí", "thăm dò khai thác dầu khí",
        "cơ khí dầu khí",
    ],

    # ── Lọc hóa dầu (BSR) ──
    "loc_hoa_dau": [
        "lọc dầu", "nhà máy lọc dầu", "dung quất", "crack spread",
        "biên lọc dầu", "xăng dầu thành phẩm", "lọc hóa dầu",
    ],

    # ── Phân phối xăng dầu (PLX) ──
    "phan_phoi_xang_dau": [
        "giá bán lẻ xăng", "cửa hàng xăng dầu", "kinh doanh xăng dầu",
        "chiết khấu xăng dầu", "quỹ bình ổn xăng", "đại lý xăng dầu",
        "điều hành giá xăng",
    ],

    # ── Khí đốt (GAS) ──
    "khi_dot": [
        "khí thiên nhiên", "khí hóa lỏng", "lng", "lpg", "khí đốt",
        "giá khí", "mua bán khí", "kho cảng lng", "khí thấp áp",
    ],

    # ── Sản xuất & phân phối điện (NT2, POW, REE) ──
    "dien": [
        "phát điện", "nhà máy điện", "thủy điện", "nhiệt điện",
        "điện khí", "sản lượng điện", "huy động điện", "giá điện",
        "thị trường điện cạnh tranh", "eptc", "hợp đồng mua bán điện",
        "phụ tải điện", "điện gió", "điện mặt trời",
    ],

    # ── Phân bón & hóa chất nông nghiệp (DCM, DPM, LAS) ──
    "phan_bon": [
        "phân bón", "phân đạm", "phân ure", "giá ure", "phân lân",
        "phân npk", "phân dap", "supe lân", "thuế vat phân bón",
        "xuất khẩu phân bón",
    ],

    # ── Cao su thiên nhiên (GVR, PHR) ──
    "cao_su": [
        "cao su thiên nhiên", "giá cao su", "mủ cao su", "xuất khẩu cao su",
        "vườn cao su", "chuyển đổi đất cao su", "khu công nghiệp cao su",
    ],

    # ── Chăn nuôi & nông nghiệp (BAF, DBC, HAG) ──
    "chan_nuoi": [
        "giá heo hơi", "giá lợn hơi", "chăn nuôi heo", "chăn nuôi lợn",
        "dịch tả lợn", "dịch tả heo châu phi", "trang trại heo",
        "giá thức ăn chăn nuôi", "đàn heo", "đàn lợn", "chăn nuôi gia súc",
    ],

    # ── Thủy sản (ANV, VHC) ──
    "thuy_san": [
        "thủy sản", "cá tra", "cá basa", "tôm xuất khẩu", "xuất khẩu cá tra",
        "xuất khẩu thủy sản", "thuế chống bán phá giá cá tra", "cá ngừ",
        "vasep", "phi lê cá tra",
    ],

    # ── Mía đường (SBT, SLS) ──
    "duong": [
        "mía đường", "giá đường", "ngành đường", "đường tinh luyện",
        "chống bán phá giá đường", "đường nhập lậu", "vùng nguyên liệu mía",
        "giá mía", "hạn ngạch đường",
    ],

    # ── Bia & đồ uống (SAB) ──
    "bia_do_uong": [
        "ngành bia", "tiêu thụ bia", "thuế tiêu thụ đặc biệt bia",
        "nồng độ cồn", "thị trường bia", "sản lượng bia",
    ],

    # ── Cảng biển & vận tải biển (DXP, GMD, VSC) ──
    "cang_bien": [
        "cảng biển", "cảng nước sâu", "sản lượng container", "teu",
        "hãng tàu", "cước vận tải biển", "logistics cảng", "cái mép",
        "lạch huyện", "phí xếp dỡ", "khai thác cảng",
    ],

    # ── Hàng không (VJC) ──
    "hang_khong": [
        "hàng không", "hãng bay", "vé máy bay", "đường bay",
        "slot bay", "đội tàu bay", "vận tải hàng không", "sân bay",
    ],

    # ── Công nghệ thông tin & phần mềm (CMG, FPT) ──
    "cong_nghe": [
        "chuyển đổi số", "phần mềm", "công nghệ thông tin",
        "trung tâm dữ liệu", "data center", "xuất khẩu phần mềm",
        "gia công phần mềm", "trí tuệ nhân tạo doanh nghiệp",
        "hạ tầng số", "dịch vụ cntt",
    ],

    # ── Phân phối & bán lẻ ICT (DGW, FRT, PSD) ──
    "phan_phoi_ict": [
        "bán lẻ điện thoại", "phân phối điện thoại", "chuỗi nhà thuốc",
        "bán lẻ công nghệ", "phân phối laptop", "ủy quyền apple",
        "bán lẻ dược phẩm",
    ],

    # ── Dược phẩm & thiết bị y tế (DP3, DVM, IMP) ──
    "duoc_pham": [
        "ngành dược", "sản xuất thuốc", "dược phẩm", "thuốc generic",
        "đấu thầu thuốc", "nhà máy dược", "eu-gmp", "gmp-who",
        "nguyên liệu dược", "vắc xin",
    ],

    # ── Dệt may (TNG) ──
    "det_may": [
        "dệt may", "ngành may", "đơn hàng dệt may", "xuất khẩu dệt may",
        "sợi dệt", "hàng may mặc", "gia công may", "kim ngạch dệt may",
    ],
}


# ─── API ────────────────────────────────────────────────────────────────────

def topics_of(sector_key: str) -> list[str]:
    return list(SECTOR_TOPICS.get(sector_key, []))


def match_sectors(text: str) -> dict[str, list[str]]:
    """
    Dò text → {sector_key: [cụm khớp]}. Chỉ gồm nhóm có ≥1 cụm khớp.
    Caller tự lấy symbols_of(sector_key) và áp TOPIC_DECAY.
    """
    if not text:
        return {}
    t = text.lower()
    hits: dict[str, list[str]] = {}
    for sector, phrases in SECTOR_TOPICS.items():
        matched = [p for p in phrases if p in t]
        if matched:
            hits[sector] = matched
    return hits


def validate(sector_keys: set[str] | None = None) -> dict:
    """
    Kiểm tra tính nhất quán:
      cross_conflicts : cụm xuất hiện ở >1 nhóm (PHẢI rỗng)
      dup_in_sector   : cụm lặp trong cùng 1 nhóm
      unknown_sectors : sector_key không có trong sector_map (nếu truyền vào)
      empty_lists     : nhóm khai báo nhưng list rỗng
    """
    phrase_owners: dict[str, list[str]] = {}
    dup_in_sector: dict[str, list[str]] = {}
    empty_lists: list[str] = []

    for sector, phrases in SECTOR_TOPICS.items():
        if not phrases:
            empty_lists.append(sector)
        seen = set()
        for p in phrases:
            if p in seen:
                dup_in_sector.setdefault(sector, []).append(p)
            seen.add(p)
            phrase_owners.setdefault(p, []).append(sector)

    cross = {p: owners for p, owners in phrase_owners.items() if len(owners) > 1}

    out = {
        "n_sectors_with_topics": len(SECTOR_TOPICS),
        "n_phrases": sum(len(v) for v in SECTOR_TOPICS.values()),
        "cross_conflicts": cross,
        "dup_in_sector": dup_in_sector,
        "empty_lists": empty_lists,
        "unknown_sectors": [],
    }
    if sector_keys is not None:
        out["unknown_sectors"] = sorted(set(SECTOR_TOPICS) - set(sector_keys))
    return out
