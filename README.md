# VNStock Signals

Pipeline thu thập/chấm điểm cổ phiếu Việt Nam và dashboard Next.js để theo dõi tín hiệu, lịch sử, phân tích và chất lượng IC.

## Thành phần chính

- Pipeline Python và ledger: `steps/`, `scripts/`, `output/history/`
- Workflow chạy thủ công/n8n: `.github/workflows/`
- Dashboard: `web/`
- Database schema: `supabase/migrations/`
- Trạng thái dự án: `PROJECT_STATE.md`

Dashboard production: <https://trading-snapshot-dl.vercel.app>

Các scoring version dùng để đối chiếu: `v4.18`, `v4.17`, `v4.9`, `v4.8`, `v4.1`, `v2.3`.

## Kiểm tra dashboard

```bash
cd web
npm ci
npm run check
```

Xem `web/README.md` để chạy local và `docs/DATA_RETENTION.md` để hiểu chính sách lưu dữ liệu/cache.
