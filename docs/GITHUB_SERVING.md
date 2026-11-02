# GitHub serving cho dashboard

Kiến trúc này giữ Supabase cho Auth và nguồn dữ liệu vận hành. GitHub chỉ chứa snapshot JSON đọc nhanh; mọi lỗi hoặc release thiếu file đều tự fallback về Supabase. Các workflow run/scoring hiện tại không bị thay đổi.

## Luồng vận hành

1. Chạy workflow thủ công **Build dashboard serving snapshots** sau khi muốn cập nhật bản GitHub.
2. Script đọc Supabase ở chế độ read-only, ghi vào staging, kiểm tra JSON/kích thước/hash rồi mới đổi `current` và giữ một bản `previous`.
3. Workflow chỉ commit `output/serving`; nếu có cấu hình revalidate thì Vercel bỏ cache cũ.
4. Owner dùng công tắc `Supabase / GitHub` trên dashboard để đối chiếu. Cookie chỉ áp dụng cho trình duyệt đó; mặc định vẫn là `DASHBOARD_DATA_SOURCE`.

## Secrets và biến môi trường

- GitHub Actions: `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
- Tùy chọn revalidate: `DASHBOARD_REVALIDATE_URL` (URL `/api/revalidate`) và `DASHBOARD_REVALIDATE_SECRET`.
- Vercel: `DASHBOARD_DATA_SOURCE=supabase`, `GITHUB_SERVING_BASE_URL` trỏ tới thư mục raw `output/serving/current` và `DASHBOARD_REVALIDATE_SECRET`.

Service-role key chỉ nằm trong GitHub Actions/Vercel server environment, không dùng tiền tố `NEXT_PUBLIC_` và không được ghi vào snapshot.

## Kiểm tra trước khi chuyển mặc định

- Mở lần lượt Today, Buy, Phân tích, Lịch sử và IC ở cả hai nguồn.
- Đối chiếu version, ngày run, số dòng và một số mã mẫu.
- Kiểm tra `manifest.json`, đặc biệt `bytes` và `sha256`.
- Giữ Supabase làm mặc định ít nhất vài chu kỳ; GitHub có thể được chọn thủ công ngay từ đầu.

## Khôi phục

Đổi công tắc về Supabase là khôi phục tức thời. Nếu release GitHub lỗi, ứng dụng cũng fallback tự động. Bản `output/serving/previous` được giữ để điều tra/khôi phục dữ liệu mà không cần đụng vào các run.
