# utils/sector_map.py
# ============================================================================
# PHÂN NGÀNH TỰ ĐỊNH NGHĨA cho rổ 130 mã (VN100 + HNX30)
# ============================================================================
# LÝ DO KHÔNG DÙNG ICB (bằng chứng diag_universe_industries 24/07/2026):
#   - Nhãn ICB trong dữ liệu là CẤP 2 (rộng), bộ từ khóa viết theo CẤP 3
#     → 27/37 khóa chưa bao giờ khớp; 41/130 mã (32%) vĩnh viễn không nhận
#       được điểm ngành.
#   - ICB cấp 2 trộn ngành nghề không liên quan, kể cả nhóm nhỏ nhất:
#       "Hàng cá nhân & Gia dụng" = PNJ (vàng bạc) + TNG (dệt may)
#       "Du lịch và Giải trí"     = SCS (hàng hóa hàng không) + VJC + VPL
#       "Tài nguyên Cơ bản"       = HPG/HSG/NKG (thép) + TMB/TVD (than) + CAP
#     → khủng hoảng kim cương nếu cộng theo ICB sẽ chạm oan TNG.
#
# QUY TẮC (chốt 24/07/2026):
#   1. MỖI MÃ THUỘC ĐÚNG MỘT NHÓM — lấy mảng kinh doanh CHÍNH.
#      HDG/TCH/VIC → bất động sản. REE → điện (lợi nhuận chính từ điện).
#   2. GỘP theo yêu cầu: BĐS nhà ở + BĐS khu công nghiệp → một nhóm;
#      xây dựng + vật liệu xây dựng → một nhóm.
#   3. scope KHAI BÁO RÕ, không suy ra từ số mã:
#        "narrow" → tin chủ đề ĐI VÀO điểm từng mã
#        "wide"   → CHỈ vào nhánh "nhiệt độ ngành", KHÔNG cộng điểm mã
#      (tránh lặp lỗi cược-ngành của QUALITY_BUY: 63% tín hiệu rơi vào
#       nhóm tài chính do ngưỡng tuyệt đối tự thưởng cho ngân hàng)
#      Số mã chỉ là tham chiếu — xem GHI CHÚ SCOPE ở cuối file cho các
#      nhóm mà scope KHÁC với suy luận thuần theo số lượng.
# ============================================================================

SECTORS: dict[str, dict] = {

    # ══════ TÀI CHÍNH ══════
    "ngan_hang": {
        "name": "Ngân hàng",
        "scope": "wide",
        "symbols": ["ACB", "BID", "CTG", "EIB", "HDB", "LPB", "MBB", "MSB",
                    "NAB", "OCB", "SHB", "SSB", "STB", "TCB", "TPB", "VCB",
                    "VIB", "VPB"],
    },
    "chung_khoan": {
        "name": "Công ty chứng khoán",
        "scope": "wide",
        "symbols": ["BSI", "BVS", "CTS", "DSE", "FTS", "HCM", "MBS", "SHS",
                    "SSI", "VCI", "VFS", "VIX", "VND"],
    },
    "tai_chinh_khac": {
        "name": "Tài chính khác (cho thuê, tín dụng)",
        "scope": "narrow",
        "symbols": ["EVF"],
    },
    "bao_hiem": {
        "name": "Bảo hiểm",
        "scope": "narrow",
        "symbols": ["BVH"],
    },

    # ══════ BẤT ĐỘNG SẢN (đã gộp nhà ở + KCN) ══════
    "bat_dong_san": {
        "name": "Bất động sản (nhà ở, thương mại, khu công nghiệp)",
        "scope": "wide",
        "symbols": ["BCM", "CEO", "DIG", "DTD", "DXG", "HDC", "HDG", "IDC",
                    "IDV", "KBC", "KDH", "KOS", "NDN", "NLG", "NVL", "PDR",
                    "SIP", "SJS", "SZC", "TCH", "VHM", "VIC", "VPI"],
    },
    "bds_cho_thue_ban_le": {
        "name": "BĐS cho thuê bán lẻ (mặt bằng TTTM)",
        "scope": "narrow",
        "symbols": ["VRE"],
    },
    "moi_gioi_bds": {
        "name": "Môi giới & dịch vụ BĐS",
        "scope": "narrow",
        "symbols": ["DXS"],
    },

    # ══════ XÂY DỰNG & VẬT LIỆU (đã gộp) ══════
    "xay_dung_vat_lieu": {
        "name": "Xây dựng & vật liệu xây dựng",
        "scope": "wide",
        "symbols": ["BMP", "CII", "CTD", "HHV", "HT1", "L14", "L18", "LHC",
                    "NTP", "VC3", "VCG", "VCS", "VGC"],
    },
    "xay_lap_dien_vt": {
        "name": "Xây lắp điện & hạ tầng viễn thông",
        "scope": "narrow",
        "symbols": ["CTR", "PC1"],
    },

    # ══════ KIM LOẠI & KHOÁNG SẢN ══════
    "thep": {
        "name": "Thép",
        "scope": "narrow",
        "symbols": ["HPG", "HSG", "NKG"],
    },
    "than_khoang_san": {
        "name": "Than & khoáng sản",
        "scope": "narrow",
        "symbols": ["TMB", "TVD"],
    },

    # ══════ DẦU KHÍ & NĂNG LƯỢNG ══════
    "dv_dau_khi": {
        "name": "Dịch vụ & thiết bị dầu khí",
        "scope": "narrow",   # 4 mã nhưng cùng chu kỳ giá dầu → xem GHI CHÚ
        "symbols": ["PVB", "PVC", "PVD", "PVS"],
    },
    "loc_hoa_dau": {
        "name": "Lọc hóa dầu",
        "scope": "narrow",
        "symbols": ["BSR"],
    },
    "phan_phoi_xang_dau": {
        "name": "Phân phối xăng dầu",
        "scope": "narrow",
        "symbols": ["PLX"],
    },
    "khi_dot": {
        "name": "Khí đốt",
        "scope": "narrow",
        "symbols": ["GAS"],
    },
    "van_tai_dau_khi": {
        "name": "Vận tải dầu khí & hóa chất",
        "scope": "narrow",
        "symbols": ["PVT"],
    },
    "dien": {
        "name": "Sản xuất & phân phối điện",
        "scope": "narrow",
        "symbols": ["NT2", "POW", "REE"],
    },
    "nuoc": {
        "name": "Cấp nước & môi trường",
        "scope": "narrow",
        "symbols": ["BWE"],
    },
    "thiet_bi_dien": {
        "name": "Thiết bị điện & dây cáp",
        "scope": "narrow",
        "symbols": ["GEE", "GEX"],
    },

    # ══════ HÓA CHẤT & NÔNG NGHIỆP ══════
    "phan_bon": {
        "name": "Phân bón & hóa chất nông nghiệp",
        "scope": "narrow",
        "symbols": ["DCM", "DPM", "LAS"],
    },
    "cao_su": {
        "name": "Cao su thiên nhiên",
        "scope": "narrow",
        "symbols": ["GVR", "PHR"],
    },
    "hoa_chat_khac": {
        "name": "Hóa chất khác (dầu nhờn, nhựa đường)",
        "scope": "narrow",
        "symbols": ["PLC"],
    },
    "chan_nuoi": {
        "name": "Chăn nuôi & nông nghiệp",
        "scope": "narrow",
        "symbols": ["BAF", "DBC", "HAG"],
    },
    "thuy_san": {
        "name": "Thủy sản",
        "scope": "narrow",
        "symbols": ["ANV", "VHC"],
    },
    "duong": {
        "name": "Mía đường",
        "scope": "narrow",
        "symbols": ["SBT", "SLS"],
    },
    "thuc_pham": {
        "name": "Thực phẩm & hàng tiêu dùng",
        "scope": "wide",     # 4 mã nhưng rất khác nhau → xem GHI CHÚ
        "symbols": ["KDC", "MSN", "PAN", "VNM"],
    },
    "bia_do_uong": {
        "name": "Bia & đồ uống",
        "scope": "narrow",
        "symbols": ["SAB"],
    },
    "lam_san_giay": {
        "name": "Lâm sản & giấy",
        "scope": "narrow",
        "symbols": ["CAP"],
    },

    # ══════ VẬN TẢI & LOGISTICS ══════
    "cang_bien": {
        "name": "Cảng biển & vận tải biển",
        "scope": "narrow",
        "symbols": ["DXP", "GMD", "VSC"],
    },
    "hang_khong": {
        "name": "Hàng không",
        "scope": "narrow",
        "symbols": ["VJC"],
    },
    "dv_hang_hoa_hang_khong": {
        "name": "Dịch vụ hàng hóa hàng không",
        "scope": "narrow",
        "symbols": ["SCS"],
    },
    "chuyen_phat": {
        "name": "Chuyển phát & logistics",
        "scope": "narrow",
        "symbols": ["VTP"],
    },
    "o_to": {
        "name": "Ô tô & hạ tầng giao thông",
        "scope": "narrow",
        "symbols": ["HUT"],
    },

    # ══════ CÔNG NGHỆ, BÁN LẺ, KHÁC ══════
    "cong_nghe": {
        "name": "Công nghệ thông tin & phần mềm",
        "scope": "narrow",
        "symbols": ["CMG", "FPT"],
    },
    "phan_phoi_ict": {
        "name": "Phân phối & bán lẻ ICT",
        "scope": "narrow",
        "symbols": ["DGW", "FRT", "PSD"],
    },
    "ban_le_dien_may": {
        "name": "Bán lẻ điện máy & tiêu dùng",
        "scope": "narrow",
        "symbols": ["MWG"],
    },
    "vang_bac_trang_suc": {
        "name": "Vàng bạc, trang sức, đá quý",
        "scope": "narrow",
        "symbols": ["PNJ"],
    },
    "det_may": {
        "name": "Dệt may",
        "scope": "narrow",
        "symbols": ["TNG"],
    },
    "duoc_pham": {
        "name": "Dược phẩm & thiết bị y tế",
        "scope": "narrow",
        "symbols": ["DP3", "DVM", "IMP"],
    },
    "du_lich_nghi_duong": {
        "name": "Du lịch & nghỉ dưỡng",
        "scope": "narrow",
        "symbols": ["VPL"],
    },
}

# ─── GHI CHÚ SCOPE (nhóm có scope khác suy luận thuần theo số mã) ───────────
SCOPE_NOTES: dict[str, str] = {
    "dv_dau_khi": (
        "4 mã nhưng để NARROW: PVB/PVC/PVD/PVS đều là nhà thầu dịch vụ cho "
        "PVN, cùng chịu chu kỳ giá dầu và tiến độ dự án thượng nguồn "
        "(Lô B, Cá Voi Xanh). Tin ngành ăn vào cả 4 là ĐÚNG bản chất."
    ),
    "thuc_pham": (
        "4 mã nhưng để WIDE: VNM (sữa), MSN (tiêu dùng + bán lẻ WinMart), "
        "KDC (dầu ăn/kem), PAN (nông nghiệp + thủy sản) có động lực rất "
        "khác nhau. Tin 'ngành thực phẩm' không nói lên điều gì riêng cho "
        "từng mã → chỉ dùng cho nhiệt độ ngành."
    ),
    "chan_nuoi": (
        "3 mã để NARROW: BAF/DBC cùng chu kỳ giá heo hơi và giá nguyên "
        "liệu thức ăn. HAG lệch hơn (heo + chuối) — theo dõi, tách nếu "
        "thấy nhiễu."
    ),
    "dien": (
        "REE xếp vào đây thay vì thiết bị điện: lợi nhuận chính đến từ "
        "mảng điện (thủy điện, nhiệt điện) chứ không phải M&E."
    ),
}

# ─── Mã đa ngành: đã chốt lấy MẢNG CHÍNH, ghi lại để rà soát về sau ────────
MULTI_BUSINESS_NOTES: dict[str, str] = {
    "HDG": "Hà Đô: BĐS (chính) + thủy điện/điện mặt trời → bat_dong_san",
    "TCH": "Hoàng Huy: BĐS (chính) + ô tô tải → bat_dong_san",
    "VIC": "Vingroup: BĐS (chính) + VinFast → bat_dong_san",
    "REE": "REE: điện (chính) + M&E + BĐS văn phòng → dien",
    "GEX": "Gelex: thiết bị điện (chính) + KCN + nước → thiet_bi_dien",
    "HUT": "Tasco: phân phối ô tô (chính) + BOT → o_to",
    "MSN": "Masan: tiêu dùng (chính) + WinMart + khoáng sản → thuc_pham",
    "PAN": "PAN Group: nông nghiệp/thực phẩm + thủy sản → thuc_pham",
    "HAG": "HAGL: chăn nuôi heo (chính) + cây ăn trái → chan_nuoi",
    "L14": "Licogi 14: xây dựng + đầu tư tài chính → xay_dung_vat_lieu",
    "VCS": "Vicostone: đá thạch anh nhân tạo xuất khẩu → xay_dung_vat_lieu",
    "CAP": "Yên Bái: giấy đế + tinh bột sắn → lam_san_giay",
    "PSD": "Petrosetco Distribution: phân phối ICT → phan_phoi_ict",
}


# ─── API ────────────────────────────────────────────────────────────────────

def _build_symbol_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for key, d in SECTORS.items():
        for s in d["symbols"]:
            idx[s] = key
    return idx


SYMBOL_TO_SECTOR: dict[str, str] = _build_symbol_index()


def sector_of(symbol: str) -> str | None:
    """Mã nhóm ngành của 1 mã CK; None nếu chưa phân loại."""
    return SYMBOL_TO_SECTOR.get((symbol or "").strip().upper())


def sector_name(sector_key: str) -> str:
    return SECTORS.get(sector_key, {}).get("name", sector_key)


def symbols_of(sector_key: str) -> list[str]:
    return list(SECTORS.get(sector_key, {}).get("symbols", []))


def scope_of(sector_key: str) -> str:
    """'narrow' → cộng vào điểm mã | 'wide' → chỉ nhiệt độ ngành."""
    return SECTORS.get(sector_key, {}).get("scope", "wide")


def is_narrow(sector_key: str) -> bool:
    return scope_of(sector_key) == "narrow"


def narrow_sectors() -> list[str]:
    return [k for k in SECTORS if is_narrow(k)]


def wide_sectors() -> list[str]:
    return [k for k in SECTORS if not is_narrow(k)]


def validate(universe: set[str] | list[str] | None = None) -> dict:
    """
    Tự kiểm tra bảng phân ngành:
      duplicates : mã bị xếp vào >1 nhóm
      bad_scope  : nhóm khai báo scope không hợp lệ
      empty      : nhóm rỗng
      missing    : mã có trong universe nhưng chưa phân ngành
      extra      : mã đã phân ngành nhưng không còn trong universe
    """
    seen: dict[str, list[str]] = {}
    for key, d in SECTORS.items():
        for s in d["symbols"]:
            seen.setdefault(s, []).append(key)

    out = {
        "n_sectors":  len(SECTORS),
        "n_symbols":  len(SYMBOL_TO_SECTOR),
        "duplicates": {s: ks for s, ks in seen.items() if len(ks) > 1},
        "bad_scope":  [k for k, d in SECTORS.items()
                       if d.get("scope") not in ("narrow", "wide")],
        "empty":      [k for k, d in SECTORS.items() if not d.get("symbols")],
        "missing":    [],
        "extra":      [],
    }
    if universe:
        u = {str(s).strip().upper() for s in universe}
        out["missing"] = sorted(u - set(SYMBOL_TO_SECTOR))
        out["extra"]   = sorted(set(SYMBOL_TO_SECTOR) - u)
    return out
