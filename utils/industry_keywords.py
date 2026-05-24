# utils/industry_keywords.py
# ICB-based keyword mapping cho news tagging
# Key = icb_name (khớp với industry_map.json)
# Value = list keywords tiếng Việt + tiếng Anh thông dụng trên báo tài chính VN

INDUSTRY_KEYWORDS: dict[str, list[str]] = {

    # ═══════════════════════════════════════════════════
    # LEVEL 3 — Subsectors (ưu tiên match trước)
    # ═══════════════════════════════════════════════════

    # --- Dầu khí ---
    "Sản xuất Dầu khí": [
        "dầu khí", "PVN", "PetroVietnam", "khai thác dầu", "thăm dò dầu",
        "giàn khoan", "mỏ dầu", "Biển Đông dầu", "PVD", "PVS"
    ],
    "Thiết bị, Dịch vụ và Phân phối Dầu khí": [
        "dịch vụ dầu khí", "thiết bị dầu khí", "PVS", "PTSC", "phân phối dầu"
    ],
    "Năng lượng thay thế": [
        "năng lượng tái tạo", "điện mặt trời", "điện gió", "solar", "wind power",
        "năng lượng sạch", "RE100", "offshore wind", "điện tái tạo", "EVN tái tạo"
    ],

    # --- Hóa chất ---
    "Hóa chất": [
        "hóa chất", "phân bón", "DPM", "DCM", "DAP", "urê", "thuốc trừ sâu",
        "nông dược", "hóa dầu", "nhựa", "cao su", "sợi", "petrochemical"
    ],

    # --- Tài nguyên Cơ bản ---
    "Lâm nghiệp và Giấy": [
        "gỗ", "lâm sản", "giấy", "bột giấy", "đồ gỗ xuất khẩu", "chế biến gỗ",
        "VINAPACO", "lâm nghiệp"
    ],
    "Kim loại": [
        "thép", "nhôm", "kim loại", "HRC", "phôi thép", "Hòa Phát", "HPG",
        "Formosa", "Pomina", "NKG", "HSG", "thép cuộn", "thép tấm",
        "kim loại màu", "đồng", "kẽm", "chì"
    ],
    "Khai khoáng": [
        "khai khoáng", "than", "khoáng sản", "TKV", "Vinacomin", "khai thác than",
        "vàng", "bạch kim", "đá quý", "bauxit", "titan"
    ],

    # --- Xây dựng và Vật liệu ---
    "Xây dựng và Vật liệu": [
        "xây dựng", "vật liệu xây dựng", "xi măng", "gạch", "kính xây dựng",
        "HBC", "CTD", "Vicem", "Hà Tiên", "BMP", "nội thất", "sàn gỗ",
        "thầu xây dựng", "tổng thầu", "EPC"
    ],

    # --- Hàng & Dịch vụ Công nghiệp ---
    "Hàng không & Quốc phòng": [
        "hàng không", "Vietnam Airlines", "VNA", "VietJet", "Bamboo Airways",
        "Vietravel Airlines", "máy bay", "sân bay", "ACV", "quốc phòng"
    ],
    "Hàng công nghiệp": [
        "công nghiệp", "đóng gói", "bao bì", "container", "packaging"
    ],
    "Điện tử & Thiết bị điện": [
        "điện tử", "thiết bị điện", "biến thế", "cáp điện", "Cadivi", "Thibidi",
        "bảng điện", "linh kiện điện tử", "PCB", "điện công nghiệp"
    ],
    "Công nghiệp nặng": [
        "đóng tàu", "cơ khí", "máy công nghiệp", "xe tải", "VEAM",
        "Lilama", "PVC", "tổng cục công nghiệp"
    ],
    "Vận tải": [
        "vận tải", "logistics", "cảng biển", "vận tải biển", "GMD", "HAH",
        "Viconship", "container ship", "cước vận tải", "freight",
        "kho vận", "giao nhận", "chuyển phát nhanh", "Viettel Post", "Vietnam Post"
    ],
    "Tư vấn & Hỗ trợ Kinh doanh": [
        "tư vấn", "outsourcing", "gia công", "BPO", "dịch vụ doanh nghiệp"
    ],

    # --- Ô tô ---
    "Ô tô và phụ tùng": [
        "ô tô", "xe hơi", "Toyota", "Honda", "VinFast", "THACO", "Trường Hải",
        "phụ tùng ô tô", "xe điện", "EV", "lốp xe", "SRC", "DRC", "linh kiện ô tô"
    ],

    # --- Thực phẩm và đồ uống ---
    "Bia và đồ uống": [
        "bia", "Sabeco", "Habeco", "Heineken", "bia Việt Nam", "đồ uống",
        "nước giải khát", "THP", "Pepsi", "Coca-Cola Việt Nam"
    ],
    "Sản xuất thực phẩm": [
        "thực phẩm", "nông sản", "xuất khẩu gạo", "tôm", "cá tra", "pangasius",
        "Masan", "VCF", "Vinamilk", "sữa", "mì gói", "Acecook", "Kinh Đô",
        "Bibica", "đường", "SBT", "QNS", "thủy sản", "Minh Phú", "Vĩnh Hoàn",
        "ANV", "IDI", "chăn nuôi", "thịt heo", "Vissan", "Hùng Vương"
    ],

    # --- Hàng cá nhân & Gia dụng ---
    "Hàng gia dụng": [
        "gia dụng", "đồ gia dụng", "thiết bị gia đình", "nội thất", "tủ lạnh",
        "máy giặt", "điều hòa", "điện máy", "Điện máy Xanh", "MWG"
    ],
    "Hàng cá nhân": [
        "may mặc", "dệt may", "giày dép", "thời trang", "TNG", "TCM", "VGT",
        "Vinatex", "xuất khẩu dệt may", "da giày", "Biti's"
    ],
    "Thuốc lá": [
        "thuốc lá", "Vinataba", "BAT Việt Nam", "Vinatabaco"
    ],

    # --- Y tế ---
    "Thiết bị và Dịch vụ Y tế": [
        "thiết bị y tế", "dụng cụ y tế", "bệnh viện", "phòng khám", "y tế",
        "chăm sóc sức khỏe", "Vinmec", "Medlatec", "Kim Long"
    ],
    "Dược phẩm": [
        "dược phẩm", "thuốc", "dược", "DHG", "IMP", "DBD", "Traphaco",
        "OPC", "DMC", "generic drug", "biệt dược", "nhà máy dược",
        "FDA", "GMP", "dược liệu"
    ],

    # --- Bán lẻ ---
    "Bán lẻ": [
        "bán lẻ", "siêu thị", "MWG", "The CrownX", "Winmart", "Co.opmart",
        "BigC", "Central Retail", "thương mại điện tử", "Shopee", "Lazada",
        "Tiki", "tiêu dùng nội địa", "sức mua", "doanh thu bán lẻ"
    ],

    # --- Truyền thông ---
    "Truyền thông": [
        "truyền thông", "quảng cáo", "media", "VTV", "HTV", "nội dung số",
        "báo chí", "xuất bản", "OTT", "streaming Việt Nam"
    ],

    # --- Du lịch và Giải trí ---
    "Du lịch và Giải trí": [
        "du lịch", "khách sạn", "resort", "Vinpearl", "Sun World",
        "lữ hành", "Vietravel", "Saigon Tourist", "casino", "Phú Quốc",
        "khách quốc tế", "nhà hàng", "F&B", "dịch vụ giải trí"
    ],

    # --- Viễn thông ---
    "Viễn thông": [
        "viễn thông", "Viettel", "VNPT", "Mobifone", "Vietnamobile",
        "5G", "băng thông rộng", "internet cáp quang", "thuê bao",
        "cước viễn thông", "FPT Telecom", "viễn thông cố định"
    ],

    # --- Tiện ích ---
    "Sản xuất & Phân phối Điện": [
        "điện lực", "EVN", "giá điện", "điện thương phẩm", "truyền tải điện",
        "phân phối điện", "tăng giá điện", "thiếu điện", "cắt điện",
        "NT2", "POW", "PPC", "QTP", "điện than", "thủy điện"
    ],
    "Nước & Khí đốt": [
        "nước sạch", "cấp nước", "khí đốt", "LPG", "PGD", "GAS",
        "PetroVietnam Gas", "PV Gas", "đường ống khí", "xử lý nước thải"
    ],

    # --- Tài chính ---
    "Ngân hàng": [
        "ngân hàng", "tín dụng", "lãi suất", "NHNN", "SBV", "Ngân hàng Nhà nước",
        "tăng trưởng tín dụng", "nợ xấu", "NPL", "Basel II", "Basel III",
        "VCB", "BID", "CTG", "TCB", "VPB", "MBB", "ACB", "STB",
        "HDB", "TPB", "MSB", "VIB", "LPB", "EIB",
        "room tín dụng", "NIM", "CASA", "CAR", "tiền gửi", "huy động vốn"
    ],
    "Bảo hiểm": [
        "bảo hiểm", "BVH", "bảo hiểm nhân thọ", "bảo hiểm phi nhân thọ",
        "tái bảo hiểm", "VBI", "MIC", "PTI", "phí bảo hiểm", "bồi thường"
    ],
    "Bất động sản": [
        "bất động sản", "BĐS", "chung cư", "đất nền", "dự án nhà ở",
        "Vinhomes", "Novaland", "NVL", "Khang Điền", "KDH", "Nam Long",
        "DXG", "PDR", "Hà Đô", "HDG", "Đất Xanh", "thị trường BĐS",
        "phân khúc", "tồn kho BĐS", "pháp lý dự án", "sổ đỏ",
        "luật đất đai", "Luật nhà ở", "tín dụng BĐS", "room BĐS"
    ],
    "Dịch vụ tài chính": [
        "chứng khoán", "TTCK", "VN-Index", "HNX", "UPCOM", "margin",
        "môi giới chứng khoán", "SSI", "VND", "VCI", "HCM", "VDS",
        "quỹ đầu tư", "ETF", "VinaCapital", "Dragon Capital", "VCBF",
        "thị trường phái sinh", "hợp đồng tương lai", "thanh khoản thị trường",
        "nâng hạng thị trường", "FTSE", "MSCI", "nhà đầu tư nước ngoài",
        "khối ngoại", "room ngoại", "tự doanh"
    ],

    # --- Công nghệ Thông tin ---
    "Công nghệ Thông tin": [
        "công nghệ thông tin", "CNTT", "phần mềm", "FPT", "CMC", "VNG",
        "AI", "trí tuệ nhân tạo", "chuyển đổi số", "cloud", "điện toán đám mây",
        "bán dẫn", "chip", "semiconductor", "data center", "an ninh mạng",
        "cybersecurity", "fintech", "startup công nghệ"
    ],

    # ═══════════════════════════════════════════════════
    # LEVEL 1 — Sector rộng (fallback nếu không match Level 3)
    # ═══════════════════════════════════════════════════

    "Nguyên vật liệu": [
        "nguyên vật liệu", "raw material", "giá nguyên liệu đầu vào",
        "tăng giá nguyên liệu"
    ],
    "Công nghiệp": [
        "khu công nghiệp", "KCN", "FDI", "đầu tư nước ngoài", "sản xuất công nghiệp",
        "IIP", "chỉ số sản xuất công nghiệp", "PMI"
    ],
    "Hàng Tiêu dùng": [
        "tiêu dùng", "CPI", "lạm phát tiêu dùng", "sức mua", "niềm tin người tiêu dùng"
    ],
    "Dịch vụ Tiêu dùng": [
        "dịch vụ", "ngành dịch vụ", "GDP dịch vụ"
    ],
}

# ═══════════════════════════════════════════════════
# MACRO KEYWORDS — Tin vĩ mô ảnh hưởng toàn thị trường
# Không map về 1 ngành cụ thể, dùng để tính market_news_pressure
# ═══════════════════════════════════════════════════

MACRO_KEYWORDS: dict[str, int] = {
    # Key = keyword, Value = sentiment_bias (+1 tích cực, -1 tiêu cực)

    # Chính sách tiền tệ
    "hạ lãi suất": +2,
    "cắt giảm lãi suất": +2,
    "nới lỏng tiền tệ": +2,
    "tăng lãi suất": -2,
    "thắt chặt tiền tệ": -1,
    "Fed cắt giảm": +1,
    "Fed tăng lãi": -1,

    # Tăng trưởng
    "GDP tăng": +2,
    "tăng trưởng kinh tế": +1,
    "xuất khẩu tăng": +1,
    "thặng dư thương mại": +1,
    "vốn FDI": +1,
    "PMI tăng": +1,

    # Rủi ro
    "suy thoái": -2,
    "khủng hoảng": -2,
    "lạm phát tăng": -1,
    "CPI tăng cao": -1,
    "chiến tranh thương mại": -2,
    "thuế quan": -1,
    "trừng phạt": -1,
    "vỡ nợ": -3,
    "phá sản": -2,
    "thanh tra": -1,
    "điều tra": -1,
    "bắt giữ lãnh đạo": -2,
    "bắt giữ chủ tịch": -2,
    "bắt giữ tổng giám đốc": -2,
    "khởi tố lãnh đạo": -2,
    "khởi tố doanh nghiệp": -2,

    # TTCK
    "nâng hạng thị trường": +3,
    "FTSE thăng hạng": +3,
    "MSCI nâng hạng": +3,
    "room ngoại nới": +2,
    "margin siết": -1,
}
# ═══════════════════════════════════════════════════
# NEWS TYPE KEYWORDS
# ═══════════════════════════════════════════════════

NEWS_TYPE_KEYWORDS: dict[str, list[str]] = {
    "immediate": [
        "kết quả", "báo lãi", "báo lỗ", "kỷ lục", "đột biến",
        "bắt giữ", "khởi tố", "vi phạm", "bị phạt", "bị xử phạt",
        "thâu tóm", "sáp nhập", "M&A", "phát hành thêm",
        "chia cổ tức", "trả cổ tức", "chốt danh sách",
        "công bố", "vừa công bố", "vừa ra mắt",
        "tăng đột biến", "giảm đột biến",
    ],
    "delayed": [
        "có hiệu lực", "từ ngày", "bắt đầu từ", "kể từ",
        "thông tư", "nghị định", "quyết định số", "luật",
        "lộ trình", "dự kiến", "kế hoạch", "đề xuất",
        "trình Quốc hội", "chờ phê duyệt", "chờ thông qua",
        "sẽ áp dụng", "sẽ có hiệu lực", "sẽ triển khai",
        "dự thảo", "đề án", "phương án",
        "từ tháng", "từ quý", "từ năm",
        "chính thức áp dụng", "chính thức triển khai",
    ],
    "monitoring": [
        "điều tra", "thanh tra", "xem xét", "cảnh báo",
        "rủi ro", "lo ngại", "áp lực", "theo dõi",
        "kiểm tra", "rà soát", "đánh giá lại",
        "chưa rõ", "chưa xác định", "còn chờ",
    ],
}

# ═══════════════════════════════════════════════════
# EFFECTIVE DATE PATTERNS
# Dùng để extract ngày hiệu lực từ title/sapo
# ═══════════════════════════════════════════════════

EFFECTIVE_DATE_PATTERNS: list[str] = [
    # Dạng đầy đủ: 1/6/2026, 01/06/2026, 1-6-2026
    r"từ ngày (\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
    r"có hiệu lực (\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
    r"kể từ (\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
    r"bắt đầu từ (\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
    r"áp dụng từ (\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",
    r"triển khai từ (\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})",

    # Dạng thiếu năm: 1/6, 01/06
    r"từ ngày (\d{1,2}[\/\-]\d{1,2})(?!\d)",
    r"có hiệu lực (\d{1,2}[\/\-]\d{1,2})(?!\d)",
    r"kể từ (\d{1,2}[\/\-]\d{1,2})(?!\d)",
    r"bắt đầu từ (\d{1,2}[\/\-]\d{1,2})(?!\d)",

    # Dạng tháng: "từ tháng 6", "từ tháng 6/2026"
    r"từ tháng (\d{1,2})(?:[\/\-](\d{4}))?",
    r"kể từ tháng (\d{1,2})(?:[\/\-](\d{4}))?",

    # Dạng quý: "từ quý 3", "từ quý 3/2026"
    r"từ quý (\d)[\/\-]?(\d{4})?",
]
