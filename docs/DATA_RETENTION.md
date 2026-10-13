# Chính sách lưu trữ dữ liệu dashboard

## Mục tiêu

Giữ dữ liệu đủ dài để so sánh các scoring version đang được review, đồng thời tránh để Supabase Free tăng dung lượng không kiểm soát.

## Phạm vi dữ liệu nóng

- Scoring version được giữ trên dashboard: `v4.18`, `v4.17`, `v4.9`, `v4.8`, `v4.1`, `v2.3`.
- Đồng bộ hằng ngày chỉ nên ghi các version trên; version thử nghiệm khác không được tiếp tục nhân bản vào Supabase.
- OHLC phục vụ tab Phân tích được làm mới theo cửa sổ 45 ngày.
- Ledger trong Git vẫn là nguồn dữ liệu gốc để có thể khôi phục hoặc backfill.

## Snapshot dung lượng

Ngày 2026-10-14, database dùng 339 MB (~68% mốc 500 MB). Ba bảng dashboard lớn nhất:

- `v4_signals`: 239 MB
- `v4_outcomes`: 29 MB
- `v4_ohlc`: 28 MB

Chưa cần tách project ngay. Bắt đầu chuẩn bị phương án tách khi vượt 80%; không tự động xóa lịch sử.

### Tối ưu serving payload

- Đo thực tế ngày 2026-10-14: `v4_signals` có 93.790 dòng, tổng 243 MB; riêng JSONB `breakdown` có 152 MB dữ liệu logic, trung bình 1.620 byte/dòng. Vì mỗi giá trị nhỏ hơn ngưỡng TOAST mặc định, PostgreSQL giữ phần lớn inline và không nén.
- Ledger prediction JSONL hiện có khoảng 145 MB trước khi tính index/metadata; vì vậy đổi trực tiếp sang CSV không tự đưa toàn bộ dữ liệu xuống dưới 50 MB.
- Từ migration `0029`, sync chỉ ghi projection phục vụ UI và giữ toàn bộ biến số numeric cần cho Phân tích/IC. Thử trên 80.630 dòng thuộc 6 version review giảm payload JSON tuần tự từ 131,2 MB xuống 90,6 MB (31%).
- Bản ghi lossless vẫn nằm trong Git JSONL. Việc archive/xóa các version cũ trong production vẫn cần một đợt maintenance có backup và xác nhận riêng.

## Quy trình kiểm tra hằng tháng

1. Kiểm tra dung lượng database và các bảng lớn nhất trong Supabase.
2. Kiểm tra ngày mới nhất của `v4_runs`, `daily_ohlc`, `v4_outcomes`, `v4_ic_metrics` và IC theo ngành.
3. Đối chiếu số bản ghi theo scoring version; điều tra nếu version đang review không có dữ liệu mới.
4. Chỉ archive/xóa dữ liệu sau khi đã xuất bản sao, kiểm tra số dòng và có phê duyệt rõ ràng.

## Nguyên tắc an toàn

- Không có cron tự động xóa dữ liệu production.
- Không xóa ledger lịch sử trong Git.
- Không đụng tới bảng của ứng dụng khác trong Supabase project dùng chung.
- Nếu database tiến gần giới hạn gói Free, ưu tiên tách dashboard sang Supabase project riêng trước khi xóa lịch sử có giá trị.

## Cache và độ mới

- Dashboard dùng cache server 5 phút cho các scoring version đang review.
- Sau khi workflow sync hoàn tất, workflow gọi endpoint revalidation để xóa cache ngay.
- Revalidation cần cùng một giá trị secret ở Vercel (`REVALIDATE_SECRET`) và GitHub Actions (`DASHBOARD_REVALIDATE_SECRET`). Nếu chưa cấu hình, TTL 5 phút là cơ chế dự phòng.
