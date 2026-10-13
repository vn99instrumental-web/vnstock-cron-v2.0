# PROJECT_STATE.md

**Cập nhật:** 2026-10-14
**Branch production:** `main`
**Dashboard:** <https://trading-snapshot-dl.vercel.app>

## Tóm tắt

Ứng dụng production gồm pipeline Python, ledger lưu trong Git, Supabase làm lớp dữ liệu phục vụ dashboard và Next.js deploy trên Vercel. Scoring formula không thuộc phạm vi thay đổi UI/data-serving hiện tại.

## Stack và kiến trúc

- Python pipeline/workflows tạo ledger và dữ liệu đánh giá.
- Git/GitHub là nguồn lịch sử có thể backfill.
- Supabase project `mcaqnaomzoqgxccdgvls` chứa dữ liệu dashboard; project đang dùng chung với ứng dụng khác.
- Next.js App Router trong `web/`, Supabase Auth bảo vệ khu vực owner.
- Vercel deploy từ `main`; `web/vercel.json` đặt Functions tại `hnd1`.

## Scoring version được review

Theo thứ tự mới nhất: `v4.18`, `v4.17`, `v4.9`, `v4.8`, `v4.1`, `v2.3`.

Các tab Buy, Hôm nay, Lịch sử và Phân tích hỗ trợ version phù hợp. Tab IC hiển thị toàn bộ version có dữ liệu, số mẫu và thời gian cập nhật đã quy đổi sang giờ Việt Nam.

## Luồng dữ liệu

- `sync_data_daily.yml`: cập nhật OHLC 45 ngày, sync ledger gần đây, tính IC tổng và IC theo ngành.
- `sync_supabase.yml`: đồng bộ đầy đủ predictions/outcomes và các bảng IC khi cần backfill.
- `cron_weekly.yml`: hoàn thiện outcomes tuần, IC tổng và IC theo ngành.
- Workflow không có lịch schedule bắt buộc; n8n là bộ điều phối bên ngoài.
- Sau sync, workflow gọi `/api/revalidate`; cặp secret GitHub/Vercel đã cấu hình và được kiểm chứng bằng workflow thật. TTL 5 phút vẫn là cơ chế dự phòng.

## Mốc cải thiện 2026-10-14

- Dùng truy vấn metadata mới nhất theo từng version thay vì tải hàng nghìn run.
- Sửa tab Hôm nay dùng đúng version đang chọn; thêm panel trạng thái độ mới dữ liệu mà không thay header.
- Lịch sử lọc đúng version và outcome join theo version, tránh trộn bản ghi cùng mã/thời điểm.
- Phân tích tải tập gần nhất và hỗ trợ tìm chính xác toàn bộ lịch sử theo mã.
- Hiển thị riêng lỗi truy vấn và trạng thái không có dữ liệu.
- Tối ưu bảng IC trên mobile, bổ sung dark/light/system theme.
- Bổ sung revalidation có secret, CI lint/typecheck/build và cấu hình region Vercel.
- Migration `0028_optimize_app_settings_policy.sql` đã áp dụng để tối ưu RLS policy bằng `(select auth.jwt())`.
- Chuẩn hóa lint cho Next.js 15 và bổ sung `npm run check`.
- Thu gọn `v4_signals.breakdown` thành serving projection: giữ field UI/drill-down và toàn bộ biến numeric cho Phân tích/IC; ledger Git vẫn là nguồn lossless. Kiểm thử trên 80.630 signal thuộc 6 version review cho thấy JSON payload giảm 31%.
- Migration `0029_compact_signal_serving_payload.sql` tăng tần suất autovacuum/analyze cho `v4_signals`; cấu hình đã áp dụng production.

## Bảo mật và dữ liệu

- Client chỉ dùng Supabase anon/publishable key; service-role key chỉ nằm trong workflow/server-side scripts.
- Endpoint revalidation dùng secret server-only và so sánh constant-time.
- Không có tác vụ tự động xóa production data. Chính sách chi tiết: `docs/DATA_RETENTION.md`.
- Không tự sửa/xóa bảng của ứng dụng khác trong Supabase project dùng chung.

## Cấu hình cần xác nhận ngoài repo

- DONE — Vercel `REVALIDATE_SECRET` và GitHub `DASHBOARD_REVALIDATE_SECRET` đã được đặt cùng giá trị, lưu dạng secret và không ghi vào repo.
- DONE — Vercel “Ignored Build Step” = `git diff HEAD^ HEAD --quiet -- .`; Functions region = `hnd1`.
- Nếu Supabase tiến gần giới hạn dung lượng, ưu tiên tạo project riêng cho dashboard; đây là thay đổi hạ tầng cần owner/billing và migration có kiểm soát.

## Kiểm chứng trước bàn giao

- PASS — YAML parse: 12 workflow.
- PASS — ESLint không có warning/error.
- PASS — TypeScript `tsc --noEmit`.
- PASS — Next.js production build, 9 static pages và các dynamic route được tạo thành công.
- PASS — security review route revalidation, truy vấn mới và Supabase policy; không có secret client-side hay advisory mới thuộc dashboard.
- PASS — production deployment `dpl_2DVC47gS7ApgLVddiVx2ygS8QKHD` READY tại region `hnd1`; endpoint revalidation trả `401` khi thiếu token.
- PASS — GitHub Actions run `38445496196`: OHLC, ledger, IC tổng, IC theo ngành và revalidation đều success.
- PASS — sau run: IC tổng `2026-10-13 18:25:51 UTC`, IC ngành `2026-10-13 18:25:57 UTC`, 136 dòng IC tổng và 14.456 dòng IC ngành.
- Hạn chế — production route sau đăng nhập cần session owner để visual QA đầy đủ.

## Việc tiếp theo

- Theo dõi dung lượng Supabase hằng tháng theo `docs/DATA_RETENTION.md`; snapshot 2026-10-14 là 339 MB (~68% mốc 500 MB).
- Tách Supabase project khi cần độc lập quota hoặc isolation với các ứng dụng khác.
