"""
utils/news_sources.py — Khai báo 5 nguồn tin chứng khoán (RSS-only)
====================================================================
Thay việc crawl qua package vnstock_news. Mỗi nguồn khai báo:
  - name   : tên hiển thị (dùng làm 'source' trong mỗi bài)
  - weight : trọng số nguồn (dùng cho weighted_sentiment; SCORING để sau)
  - feeds  : list URL RSS (một nguồn có thể có nhiều feed chuyên mục)

QUY TẮC (đã chốt):
  - A3: chỉ PHÁT HIỆN bài qua RSS (KHÔNG cào trang mục HTML)
  - Feed nào chết (404/timeout) → news_rss tự bỏ qua + log, không chặn feed khác
  - Thêm/bớt nguồn = sửa DUY NHẤT file này

Trạng thái feed (kiểm chứng 2026-07):
  [OK]    đã xác nhận hoạt động thực tế
  [PROBE] feed đoán theo cấu trúc site — nếu chết sẽ tự bị bỏ qua (xem log)
"""

SOURCES: list[dict] = [
    {
        "name": "cafef",
        "weight": 1.3,
        "feeds": [
            "https://cafef.vn/thi-truong-chung-khoan.rss",   # [OK]
            "https://cafef.vn/doanh-nghiep.rss",             # [PROBE] chuẩn CafeF
            "https://cafef.vn/tai-chinh-ngan-hang.rss",      # [PROBE] chuẩn CafeF
        ],
    },
    {
        "name": "vietstock",
        "weight": 1.3,
        "feeds": [
            "https://vietstock.vn/830/chung-khoan/co-phieu.rss",         # [OK]
            "https://vietstock.vn/739/chung-khoan/giao-dich-noi-bo.rss", # [OK]
            "https://vietstock.vn/737/doanh-nghiep.rss",                 # [PROBE]
        ],
    },
    {
        "name": "vneconomy",
        "weight": 1.1,
        "feeds": [
            "https://vneconomy.vn/chung-khoan.rss",   # [OK]
            "https://vneconomy.vn/tai-chinh.rss",     # [PROBE]
        ],
    },
    {
        "name": "baodautu",
        "weight": 1.2,
        "feeds": [
            "https://baodautu.vn/rss/tai-chinh-chung-khoan.rss",  # [PROBE] chuyên CK
            "https://baodautu.vn/rss/doanh-nghiep.rss",           # [PROBE]
            "https://baodautu.vn/rss/tin-moi-nhat.rss",           # [OK] fallback tổng
        ],
    },
    {
        "name": "thitruongtaichinh",
        "weight": 1.0,
        "feeds": [
            "https://thitruongtaichinh.kinhtedothi.vn/rss/chung-khoan-182.rss",  # [OK]
        ],
    },
]

# Giới hạn số bài lấy mỗi feed mỗi lần (tránh feed trả quá dài)
LIMIT_PER_FEED = 40

# Cửa sổ lưu lịch sử (ngày) — dùng cho de-dup + cache body + tính index
HISTORY_DAYS = 30
