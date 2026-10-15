# VNStock Signals

Pipeline thu thập/chấm điểm cổ phiếu Việt Nam và dashboard Next.js để theo dõi tín hiệu, lịch sử, phân tích và chất lượng IC.

## Thành phần chính

- Pipeline Python và ledger: `steps/`, `scripts/`, `output/history/`
- Workflow chạy thủ công/n8n: `.github/workflows/`
- Dashboard: `web/`
- Database schema: `supabase/migrations/`
- Trạng thái dự án: `PROJECT_STATE.md`

Dashboard production: <https://trading-snapshot-dl.vercel.app>

Các scoring version dùng để đối chiếu: `v4.19-shadow`, `v4.18`, `v4.17`, `v4.9`, `v4.8`, `v4.1`, `v2.3`. `v4.18` vẫn là production mặc định; `v4.19-shadow` chỉ forward-test, dùng trọng số IC cố định MeanRev/Breakout/Flow/Fund/Growth = 5/15/20/25/35 và không phát thông báo. Phương pháp và cách monitor: `docs/V419_SHADOW_WEIGHTING.md`.

## Kiểm tra dashboard

```bash
cd web
npm ci
npm run check
```

Xem `web/README.md` để chạy local và `docs/DATA_RETENTION.md` để hiểu chính sách lưu dữ liệu/cache.

## Cập nhật dashboard insight 2026-10-14

Dashboard dùng lớp snapshot phục vụ riêng cho các phép chẩn đoán nặng; workflow daily refresh snapshot sau khi đồng bộ ledger/IC và trước khi xóa cache Vercel. Header hiện tại được giữ nguyên, còn insight ưu tiên được đặt ngay dưới tiêu đề từng trang.
