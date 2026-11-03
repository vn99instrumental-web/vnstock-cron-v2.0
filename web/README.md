# VNStock Signals Dashboard

Dashboard Next.js App Router + TypeScript + Tailwind, đọc dữ liệu public từ Supabase và dùng Supabase Auth cho khu vực owner.

## Chạy local

```bash
cp .env.local.example .env.local
npm ci
npm run dev
```

Các biến public chỉ gồm URL, anon key và owner email. Không đưa Supabase service-role key vào ứng dụng web.

## Kiểm tra

```bash
npm run lint
npm run typecheck
npm run build
# hoặc chạy cả ba
npm run check
```

## Dữ liệu và cache

- GitHub serving là nguồn mặc định; hai nút GitHub/Supabase đọc đúng nguồn đã chọn và không fallback âm thầm.
- Supabase tiếp tục cung cấp Auth và làm mirror non-blocking trong giai đoạn chuyển đổi.
- GitHub snapshots được tạo trực tiếp từ ledger cùng commit với mỗi intraday run.
- Cache server có TTL 5 phút cho mọi scoring version đang review.
- `POST /api/revalidate` xóa cache sau khi workflow sync thành công; endpoint yêu cầu bearer token `REVALIDATE_SECRET`.
- GitHub Actions dùng secret `DASHBOARD_REVALIDATE_SECRET` có cùng giá trị.

## Deploy

Project được deploy từ nhánh `main` lên Vercel. `vercel.json` đặt Functions tại region Tokyo (`hnd1`) để gần Supabase hơn.

## Lớp dữ liệu phục vụ

- `v4_analysis_diagnostics_snapshot` thay các phép tương quan nặng trên request bằng snapshot nhỏ được tạo sau daily sync.
- `v4_dashboard_version_summary` cung cấp coverage ngày/số dòng theo version để tránh so sánh sai cửa sổ.
- Tab Phân tích có chế độ `Cùng cửa sổ`; tab IC hiển thị toàn bộ version và phạm vi dữ liệu, không dùng hộp chọn version.
