"""
utils/news_sentiment.py — Cảm xúc tin (rule-based, TÁCH RIÊNG)
==============================================================
Tách riêng có chủ đích: đây là chỗ DỄ NÂNG CẤP sau (đổi sang phrase-based,
từ điển lớn hơn, hoặc model) mà KHÔNG phải đụng news_enrich / aggregate / scoring.

Hiện tại: đếm từ khóa tích cực − tiêu cực (giữ nguyên logic bản cũ đã dùng).
Trả về SỐ THÔ (không giới hạn thang); việc quy về điểm để aggregate/scoring lo.

Nâng cấp sau ví dụ:
  - Chuyển sang cụm từ có hướng ("báo lãi kỷ lục" = +2, "bị bán tháo" = -2)
  - Trọng số theo vị trí (tiêu đề nặng hơn mô tả)
  - Chỉ cần giữ nguyên chữ ký hàm score_sentiment(text) -> float
"""

POSITIVE_WORDS = [
    "tăng", "tích cực", "khởi sắc", "hưởng lợi", "cơ hội",
    "tăng trưởng", "vượt kỳ vọng", "lợi nhuận cao", "kỷ lục",
    "bứt phá", "phục hồi", "tốt", "thuận lợi", "tăng mạnh",
    "lạc quan", "triển vọng", "tích lũy", "đột phá",
]

NEGATIVE_WORDS = [
    "giảm", "tiêu cực", "rủi ro", "áp lực", "sụt giảm", "thua lỗ",
    "bị phạt", "điều tra", "nợ xấu", "mất thanh khoản", "cảnh báo",
    "khó khăn", "giảm mạnh", "thất bại", "vi phạm", "bắt giữ",
    "lo ngại", "bất ổn", "suy giảm", "vỡ nợ",
]


def score_sentiment(text: str) -> float:
    """Đếm từ tích cực − tiêu cực. Trả số thô (pos - neg)."""
    t = (text or "").lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in t)
    neg = sum(1 for w in NEGATIVE_WORDS if w in t)
    return float(pos - neg)
