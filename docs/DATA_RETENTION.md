# Chính sách lưu trữ dữ liệu dashboard

## Mục tiêu

Giữ dữ liệu đủ dài để so sánh các scoring version đang được review, đồng thời tránh để Supabase Free tăng dung lượng không kiểm soát.

## Phạm vi dữ liệu nóng

- Scoring version được giữ trên dashboard: `v4.19-shadow`, `v4.18`, `v4.17`, `v4.8`, `v4.1`, `v2.3`.
- Đồng bộ hằng ngày chỉ nên ghi các version trên; version thử nghiệm khác không được tiếp tục nhân bản vào Supabase.
- OHLC phục vụ tab Phân tích được làm mới theo cửa sổ 45 ngày và giữ tối đa 900 ngày để đủ EMA200/biểu đồ.
- Ledger trong Git vẫn là nguồn dữ liệu gốc để có thể khôi phục hoặc backfill.

## Snapshot dung lượng

Ngày 2026-10-14, database dùng khoảng 350 MB (~70% mốc 500 MB). Ba bảng dashboard lớn nhất:

- `v4_signals`: 239 MB
- `v4_outcomes`: 29 MB
- `v4_ohlc`: 28 MB

Chưa cần tách project ngay. Bắt đầu chuẩn bị phương án tách khi vượt 80%; không tự động xóa lịch sử.

### Dọn dữ liệu production 2026-10-14

- Chỉ giữ 7 version review trong `v4_signals`, `v4_outcomes`, `v4_runs`, `v4_ic_metrics` và `v4_marginal_ic`.
- Xóa 13.160 signal, 5.400 outcome và 64 dòng marginal IC thuộc version không còn phục vụ UI.
- IC ngành chỉ giữ batch `ready` mới nhất; 8 batch cũ (13.376 metric) đã được xóa theo cascade.
- OHLC chỉ giữ 900 ngày: giảm từ 162.448 xuống 81.083 dòng. Khoảng trống sau DELETE được PostgreSQL tái sử dụng; kích thước file vật lý không nhất thiết giảm ngay.

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

- Mỗi lần xuất OHLC chỉ xóa nến cũ hơn 900 ngày; mỗi lần xuất IC ngành chỉ giữ snapshot `ready` mới nhất. Mọi lệnh xóa đều có filter bắt buộc.
- Không xóa ledger lịch sử trong Git; đây vẫn là nguồn khôi phục lossless.
- Không đụng tới bảng của ứng dụng khác trong Supabase project dùng chung.
- Nếu database tiến gần giới hạn gói Free, ưu tiên tách dashboard sang Supabase project riêng trước khi xóa lịch sử có giá trị.

## Cache và độ mới

- Dashboard dùng cache server 5 phút cho các scoring version đang review.
- Sau khi workflow sync hoàn tất, workflow gọi endpoint revalidation để xóa cache ngay.
- Revalidation cần cùng một giá trị secret ở Vercel (`REVALIDATE_SECRET`) và GitHub Actions (`DASHBOARD_REVALIDATE_SECRET`). Nếu chưa cấu hình, TTL 5 phút là cơ chế dự phòng.

## Snapshot phục vụ dashboard

- `v4_analysis_diagnostics_snapshot`: ghi đè toàn bộ sau daily sync; không tích lũy lịch sử.
- `v4_dashboard_version_summary`: ghi đè theo version; không tích lũy lịch sử.
- `v4_ic_daily_snapshot`: một dòng cho mỗi ngày × version × factor × horizon, giữ tối đa 400 ngày.
- Snapshot không thay ledger hoặc các bảng nguồn. Nếu refresh lỗi, dashboard vẫn có dữ liệu nguồn/cached trước đó nhưng phần chẩn đoán có thể cũ.
- Chỉ service role được gọi `refresh_v4_dashboard_snapshots()`; anon/authenticated chỉ có quyền đọc các bảng snapshot.

## Retention intraday theo scoring version

- v4.18 và v4.17: giữ toàn bộ snapshot intraday để đối chiếu trạng thái trong ngày.
- v4.19-shadow, v4.8, v4.1, v2.3: mỗi ngày giữ run cuối cùng và thêm run cuối cùng có BUY/STRONG BUY. Cách này giữ đủ breakdown cho tab Mua kể cả khi run đóng cửa không còn tín hiệu BUY, đồng thời không nhân dung lượng intraday cho candidate thử nghiệm.
- Outcomes và runs của các version daily-retention chỉ giữ khi còn liên kết với signal được giữ. Ledger Git vẫn là bản lossless để backfill.
- IC tổng, IC theo ngành và marginal IC được tính từ ledger/daily-last trước khi retention chạy; Vercel đọc các bảng precompute thay vì tính lại từ toàn bộ intraday.
- Hàm prune_v4_legacy_intraday() chỉ cấp quyền thực thi cho service_role; workflow refresh dashboard snapshot và xóa cache trước, sau đó mới chạy retention ở bước maintenance cuối.
- DELETE tạo khoảng trống để PostgreSQL tái sử dụng. Không tự chạy VACUUM FULL vì thao tác đó khóa bảng; autovacuum xử lý reclaim thông thường.
### Kết quả áp dụng production 2026-10-15

- Bốn version cũ giảm từ 66.330 xuống 11.380 signal; xóa 54.950 snapshot intraday lặp.
- Outcomes liên quan giảm từ 52.618 xuống 8.730; runs giảm từ 655 xuống 97.
- Sau DELETE, kích thước vật lý vẫn khoảng 350 MB vì PostgreSQL giữ page để tái sử dụng. Mục tiêu tức thời là chặn tăng trưởng; autovacuum sẽ thu hồi tuple chết, không chạy VACUUM FULL tự động.
### Cleanup production 2026-10-15

- Đã xóa 139 dòng v4_runs orphan của v4.17/v4.18; sau cleanup orphan run = 0.
- Không xóa thêm signal, outcome, OHLC hay IC vì toàn bộ phần còn lại có consumer hoặc nằm trong retention đã phê duyệt.
- VACUUM ANALYZE đã chạy cho v4_signals, v4_outcomes và v4_runs; dead tuple = 0. Kích thước vật lý database vẫn khoảng 350 MB và các page trống sẽ được tái sử dụng.
- VACUUM FULL chưa chạy vì cần khóa độc quyền bảng production; chỉ thực hiện trong maintenance window có phê duyệt riêng.

### Ổn định maintenance và snapshot 2026-10-16

- Retention RPC có `statement_timeout=60s` ở cấp function thay vì kế thừa 8 giây của PostgREST; script có timeout kết nối/đọc riêng và log thời gian từng RPC.
- Anti-join dọn outcome dùng bảng tạm có khóa chính theo `(scoring_version, pred_id)` và bỏ ba phép đếm toàn bảng trước DELETE. Lần chạy production xác minh hoàn tất trong khoảng 13,1 giây.
- Cả weekly, daily và manual sync đều refresh snapshot + revalidate cache trước khi chạy retention. Vì vậy lỗi maintenance không còn chặn dữ liệu dashboard mới.
- `refresh_v4_dashboard_snapshots()` có timeout 60 giây và chỉ refresh phần bắt buộc hằng ngày: factor, split, IC history và version summary. Ma trận factor-pair là thống kê khám phá rất nặng; daily refresh giữ snapshot pair thành công gần nhất thay vì làm fail toàn bộ luồng.
- Lần refresh production sau sửa hoàn tất trong khoảng 5,9 giây: 243 factor rows, 464 split rows, 272 IC-history rows, 7 version summaries; 5.150 pair rows cũ được giữ nguyên.
