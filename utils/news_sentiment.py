# utils/news_sentiment.py
# ============================================================================
# Phrase-based directional sentiment cho tin tài chính Việt Nam
# ============================================================================
# THIẾT KẾ (2026-07-19 — thay thế cơ chế đếm từ đơn cũ trong step_news_daily):
#
#   1. KHÔNG chấm từ đơn chung chung. "tăng"/"giảm" đứng một mình = 0 điểm.
#      Chỉ chấm CỤM TỪ có chủ thể + hướng rõ ràng:
#        "lợi nhuận giảm"  → tiêu cực
#        "giảm lãi suất"   → TÍCH CỰC (cơ chế cũ chấm sai thành tiêu cực)
#        "giá thép giảm"   → không nằm trong bảng → 0 (không rõ tác động)
#
#   2. Ba mức cường độ:
#        ±3 STRONG : sự kiện định giá lại cổ phiếu (khởi tố, hủy niêm yết,
#                    lãi kỷ lục, vượt kế hoạch năm...)
#        ±2 MEDIUM : sự kiện KQKD / hành động doanh nghiệp có hướng rõ
#        ±1 MILD   : tín hiệu mềm (triển vọng, áp lực chi phí...)
#
#   3. PHỦ ĐỊNH: nếu trong ~3 từ ngay trước cụm có từ phủ định
#      ("không", "chưa", "khó", "hết", "ngừng", "dừng", "chấm dứt",
#       "thoát khỏi") → ĐẢO DẤU và giảm còn 1/2 cường độ.
#        "không còn thua lỗ"  : thua lỗ(-2) → +1
#        "khó tăng trưởng lợi nhuận" : (+2) → -1
#      Đảo ×0.5 (không ×1.0) vì phủ định trong tiếng Việt báo chí thường
#      là tín hiệu yếu hơn khẳng định trực tiếp.
#
#   4. LONGEST-MATCH-FIRST + consume span: cụm dài ăn trước, vùng text đã
#      match không được chấm lại.
#        "biên lợi nhuận giảm" (-1, mild) sẽ thắng "lợi nhuận giảm" (-2)
#        → phân biệt đúng: biên giảm nhẹ hơn lợi nhuận giảm.
#
#   5. Điểm mỗi bài clamp về [-3, +3].
#
# Pure Python, không dependency ngoài stdlib → test offline được bằng
# scripts/test_news_sentiment.py (không cần mạng, không cần vnstock).
# ============================================================================
import re

# ─── Bảng cụm từ ─────────────────────────────────────────────────────────────
# Key = cụm (lowercase, sẽ match substring trên text đã normalize).
# LƯU Ý khi thêm cụm mới:
#   - Viết thường, không dấu câu
#   - Cụm phải tự đứng được về HƯỚNG (đọc cụm là biết tốt/xấu cho cổ phiếu)
#   - Cụm dài hơn tự động ưu tiên hơn cụm ngắn chồng lấn

STRONG_POS: dict[str, float] = {
    "lãi kỷ lục"             : 3,
    "lợi nhuận kỷ lục"       : 3,
    "doanh thu kỷ lục"       : 3,
    "lãi đột biến"           : 3,
    "lợi nhuận đột biến"     : 3,
    "vượt kế hoạch năm"      : 3,
    "vượt xa kế hoạch"       : 3,
    "lãi gấp"                : 3,   # "lãi gấp 3 lần cùng kỳ"
    "lợi nhuận gấp"          : 3,
}

STRONG_NEG: dict[str, float] = {
    "bị khởi tố"             : -3,
    "khởi tố chủ tịch"       : -3,
    "khởi tố tổng giám đốc"  : -3,
    "bắt tạm giam"           : -3,
    "bị bắt"                 : -3,
    "thao túng chứng khoán"  : -3,
    "thao túng giá cổ phiếu" : -3,
    "hủy niêm yết"           : -3,
    "diện kiểm soát"         : -3,
    "diện hạn chế giao dịch" : -3,
    "đình chỉ giao dịch"     : -3,
    "vỡ nợ"                  : -3,
    "mất khả năng thanh toán": -3,
    "phá sản"                : -3,
    "âm vốn chủ sở hữu"      : -3,
    "kiểm toán từ chối"      : -3,
    "ý kiến ngoại trừ"       : -3,
    "gian lận tài chính"     : -3,
}

MED_POS: dict[str, float] = {
    "lợi nhuận tăng"         : 2,
    "lãi ròng tăng"          : 2,
    "lãi tăng"               : 2,
    "doanh thu tăng"         : 2,
    "báo lãi"                : 2,
    "có lãi trở lại"         : 2,
    "thoát lỗ"               : 2,
    "trúng thầu"             : 2,
    "ký hợp đồng"            : 2,
    "ký kết hợp đồng"        : 2,
    "mua cổ phiếu quỹ"       : 2,
    "đăng ký mua"            : 2,   # cổ đông nội bộ đăng ký mua
    "cổ tức tiền mặt"        : 2,
    "tạm ứng cổ tức"         : 2,
    "hoàn thành kế hoạch"    : 2,
    "mở rộng công suất"      : 2,
    "khánh thành nhà máy"    : 2,
    "đưa vào vận hành"       : 2,
    "xuất khẩu tăng"         : 2,
    "đơn hàng tăng"          : 2,
    "nới room ngoại"         : 2,
    "được nâng hạng"         : 2,
    "nâng dự báo"            : 2,
    "khuyến nghị mua"        : 2,
    "biên lợi nhuận cải thiện": 2,
    "giảm lãi suất"          : 2,   # cơ chế cũ chấm SAI thành tiêu cực
    "hạ lãi suất"            : 2,
    "nợ xấu giảm"            : 2,
    "tăng trưởng lợi nhuận"  : 2,
    "tăng trưởng doanh thu"  : 2,
}

MED_NEG: dict[str, float] = {
    "lợi nhuận giảm"         : -2,
    "lãi ròng giảm"          : -2,
    "lãi giảm"               : -2,
    "doanh thu giảm"         : -2,
    "thua lỗ"                : -2,
    "lỗ ròng"                : -2,
    "báo lỗ"                 : -2,
    "lỗ lũy kế"              : -2,
    "lỗ nặng"                : -2,
    "nợ xấu tăng"            : -2,
    "bị phạt"                : -2,
    "bị xử phạt"             : -2,
    "truy thu thuế"          : -2,
    "cưỡng chế thuế"         : -2,
    "cắt giảm nhân sự"       : -2,
    "sa thải"                : -2,
    "đăng ký bán"            : -2,  # cổ đông nội bộ đăng ký bán
    "hoãn cổ tức"            : -2,
    "không chia cổ tức"      : -2,  # cụm riêng — thắng "chia cổ tức" (+1)
    "tăng lãi suất"          : -2,
    "nâng lãi suất"          : -2,
    "chậm tiến độ"           : -2,
    "dừng dự án"             : -2,
    "thu hồi dự án"          : -2,
    "hạ dự báo"              : -2,
    "khuyến nghị bán"        : -2,
    "giải thể"               : -2,
    "đóng cửa nhà máy"       : -2,
    "chậm công bố thông tin" : -2,
}

MILD_POS: dict[str, float] = {
    "chia cổ tức"            : 1,
    "trả cổ tức"             : 1,
    "chốt quyền cổ tức"      : 1,
    "triển vọng tích cực"    : 1,
    "khả quan"               : 1,
    "khởi sắc"               : 1,
    "phục hồi"               : 1,
    "hưởng lợi"              : 1,
    "được chấp thuận"        : 1,
    "được phê duyệt"         : 1,
    "hợp tác chiến lược"     : 1,
    "đối tác chiến lược"     : 1,
    "đầu tư mở rộng"         : 1,
    "ra mắt sản phẩm"        : 1,
}

MILD_NEG: dict[str, float] = {
    "áp lực chi phí"         : -1,
    "cạnh tranh gay gắt"     : -1,
    "khó khăn kéo dài"       : -1,
    "tồn kho tăng"           : -1,
    "chi phí tăng"           : -1,
    "biên lợi nhuận giảm"    : -1,  # dài hơn "lợi nhuận giảm" → thắng, -1
    "pha loãng cổ phiếu"     : -1,
    "rủi ro pha loãng"       : -1,
    "cảnh báo rủi ro"        : -1,
    "bị nhắc nhở"            : -1,
}

# Gộp toàn bộ, sort theo độ dài giảm dần (longest-match-first)
ALL_PHRASES: dict[str, float] = {}
for _d in (STRONG_POS, STRONG_NEG, MED_POS, MED_NEG, MILD_POS, MILD_NEG):
    ALL_PHRASES.update(_d)

_PHRASES_SORTED: list[tuple[str, float]] = sorted(
    ALL_PHRASES.items(), key=lambda kv: len(kv[0]), reverse=True
)

# ─── Lớp match 2: CHỦ THỂ + HƯỚNG cách nhau (gap ≤ 40 ký tự) ────────────────
# Tiêu đề thực tế hay chen cụm thời gian/tên công ty vào giữa:
#   "Lợi nhuận quý II của Hòa Phát giảm 30%"
# Exact phrase "lợi nhuận giảm" không bắt được → cần regex gap.
# Thứ tự QUAN TRỌNG: chủ thể dài/cụ thể hơn đứng trước (biên lợi nhuận
# trước lợi nhuận) — chạy tuần tự + consume span như lớp 1.
# Gap không vượt qua dấu câu ([^,.;:!?]) để tránh nối 2 mệnh đề khác nhau.

_GAP = r"[^,.;:!?]{0,40}?"

GAP_RULES: list[tuple[str, float]] = [
    (rf"biên lợi nhuận{_GAP}(?:giảm|thu hẹp|sụt giảm)",        -1),
    (rf"biên lợi nhuận{_GAP}(?:tăng|cải thiện|mở rộng)",        1),
    (rf"lợi nhuận{_GAP}(?:sụt giảm|lao dốc|giảm)",             -2),
    (rf"lợi nhuận{_GAP}(?:tăng|gấp|bứt phá)",                   2),
    (rf"lãi ròng{_GAP}(?:giảm|lao dốc)",                       -2),
    (rf"lãi ròng{_GAP}(?:tăng|gấp)",                            2),
    (rf"doanh thu{_GAP}(?:sụt giảm|giảm)",                     -2),
    (rf"doanh thu{_GAP}(?:tăng|gấp)",                           2),
    (rf"nợ xấu{_GAP}tăng",                                     -2),
    (rf"nợ xấu{_GAP}giảm",                                      2),
    # "lỗ" đứng cạnh con số: "lỗ 200 tỷ", "lỗ hơn 1.000 tỷ"
    (r"\blỗ (?:hơn |gần |khoảng |thêm )?\d",                   -2),
]

_GAP_COMPILED: list[tuple[re.Pattern, float]] = [
    (re.compile(pat), pts) for pat, pts in GAP_RULES
]

# ─── Phủ định ────────────────────────────────────────────────────────────────
_NEG_SINGLE = {"không", "chưa", "khó", "hết", "ngừng", "dừng"}
_NEG_MULTI  = ("chấm dứt", "thoát khỏi")
_NEG_WINDOW = 16   # số ký tự nhìn ngược trước cụm

ARTICLE_CLAMP = 3.0


def _norm(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def _is_negated(pre: str) -> bool:
    """pre = đoạn text ngay trước cụm (đã lowercase)."""
    if any(m in pre for m in _NEG_MULTI):
        return True
    words = pre.split()
    return any(w in _NEG_SINGLE for w in words[-3:])


def score_sentiment(text: str, return_evidence: bool = False):
    """
    Chấm sentiment 1 bài (title + short_description).

    Returns:
        float clamp [-3, +3]                       nếu return_evidence=False
        (float, list[(phrase, points)])            nếu return_evidence=True
    """
    t = _norm(text)
    if not t:
        return (0.0, []) if return_evidence else 0.0

    consumed: list[tuple[int, int]] = []
    total    = 0.0
    evidence: list[tuple[str, float]] = []

    for phrase, pts in _PHRASES_SORTED:
        start = 0
        while True:
            i = t.find(phrase, start)
            if i < 0:
                break
            j = i + len(phrase)
            # Chồng lấn với vùng đã match (cụm dài hơn đã ăn) → bỏ qua
            if any(not (j <= s or i >= e) for s, e in consumed):
                start = j
                continue
            consumed.append((i, j))

            pre   = t[max(0, i - _NEG_WINDOW):i]
            score = float(pts)
            if _is_negated(pre):
                score = -score * 0.5   # đảo dấu, giảm nửa cường độ

            total += score
            evidence.append((phrase, round(score, 1)))
            start = j

    # ── Lớp 2: chủ thể + hướng cách nhau (gap) ──
    for pattern, pts in _GAP_COMPILED:
        for m in pattern.finditer(t):
            i, j = m.start(), m.end()
            if any(not (j <= s or i >= e) for s, e in consumed):
                continue
            consumed.append((i, j))

            pre   = t[max(0, i - _NEG_WINDOW):i]
            score = float(pts)
            if _is_negated(pre):
                score = -score * 0.5

            total += score
            evidence.append((m.group(0)[:30], round(score, 1)))

    total = max(-ARTICLE_CLAMP, min(ARTICLE_CLAMP, total))
    total = round(total, 2)
    return (total, evidence) if return_evidence else total
