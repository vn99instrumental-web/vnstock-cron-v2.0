"""
utils/news_sources.py — Khai báo nguồn tin chứng khoán (RSS-only)
====================================================================
Thay việc crawl qua package vnstock_news. Mỗi nguồn khai báo:
  - name   : tên hiển thị (dùng làm 'source' trong mỗi bài)
  - weight : trọng số nguồn (dùng cho weighted_sentiment; SCORING để sau)
  - feeds  : list URL RSS (một nguồn có thể có nhiều feed chuyên mục)

QUY TẮC:
  - A3: chỉ PHÁT HIỆN bài qua RSS (KHÔNG cào trang mục HTML)
  - Feed nào chết (404/timeout/rỗng) → news_rss tự bỏ qua + log, không chặn
  - Thêm/bớt nguồn = sửa DUY NHẤT file này

Kiểm chứng THỰC TẾ trên GitHub runner (dry-run 2026-07-27):
  ✅ cafef      — 3 feed sống, 90 bài, 100% có mô tả
  ✅ vietstock  — 3 feed sống, 70 bài (kể cả giao dịch nội bộ)
  ✅ vneconomy  — 2 feed sống, 60 bài
  ❌ baodautu             — feed RSS rỗng (channel không có <item>) → BỎ
  ❌ thitruongtaichinh    — timeout ~40s từ runner GitHub → BỎ
  → 3 nguồn trên đã phủ 56/130 mã universe. Muốn thêm nguồn: verify feed
    có <item> rồi mới thêm vào đây (tránh feed rỗng/timeout làm chậm run).
"""

SOURCES: list[dict] = [
    {
        "name": "cafef",
        "weight": 1.3,
        "feeds": [
            "https://cafef.vn/thi-truong-chung-khoan.rss",
            "https://cafef.vn/doanh-nghiep.rss",
            "https://cafef.vn/tai-chinh-ngan-hang.rss",
        ],
    },
    {
        "name": "vietstock",
        "weight": 1.3,
        "feeds": [
            "https://vietstock.vn/830/chung-khoan/co-phieu.rss",
            "https://vietstock.vn/739/chung-khoan/giao-dich-noi-bo.rss",
            "https://vietstock.vn/737/doanh-nghiep.rss",
        ],
    },
    {
        "name": "vneconomy",
        "weight": 1.1,
        "feeds": [
            "https://vneconomy.vn/chung-khoan.rss",
            "https://vneconomy.vn/tai-chinh.rss",
        ],
    },
]

# Giới hạn số bài lấy mỗi feed mỗi lần (tránh feed trả quá dài)
LIMIT_PER_FEED = 40

# Cửa sổ lưu lịch sử (ngày) — dùng cho de-dup + cache body + tính index
HISTORY_DAYS = 30
