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

- Các trang dashboard đọc qua Supabase với RLS.
- Cache server có TTL 5 phút cho mọi scoring version đang review.
- `POST /api/revalidate` xóa cache sau khi workflow sync thành công; endpoint yêu cầu bearer token `REVALIDATE_SECRET`.
- GitHub Actions dùng secret `DASHBOARD_REVALIDATE_SECRET` có cùng giá trị.

## Deploy

Project được deploy từ nhánh `main` lên Vercel. `vercel.json` đặt Functions tại region Tokyo (`hnd1`) để gần Supabase hơn.
