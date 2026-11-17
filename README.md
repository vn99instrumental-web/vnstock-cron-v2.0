# VNStock Signals

Pipeline thu thập/chấm điểm cổ phiếu Việt Nam và dashboard Next.js để theo dõi tín hiệu, lịch sử, phân tích và chất lượng IC.

## Thành phần chính

- Pipeline Python và ledger: `steps/`, `scripts/`, `output/history/`
- Workflow chạy thủ công/n8n: `.github/workflows/`
- Dashboard: `web/`
- Database schema: `supabase/migrations/`
- Trạng thái dự án: `PROJECT_STATE.md`
- Gen 6 operations: docs/vnstock6-flow.md
- Gen 6 focused backlog: docs/VNSTOCK6_TASKS.md

Dashboard production: <https://trading-snapshot-dl.vercel.app>

## Nguồn kỹ thuật mặc định cho phân tích cổ phiếu (từ 17/11/2026)

Khi phân tích một mã cổ phiếu, đọc **Gen6** tại `output/serving/vnstock6/current/`; xác nhận version hiện hành trong `output/vnstock6/native-status.json` và `output/serving/vnstock6/current/metadata.json`. Tại mốc cập nhật: profile chính `v6.4.18`; `v6.4.19-shadow` chỉ để đối chiếu. **Không dùng tín hiệu/score V4 cũ làm dữ liệu kỹ thuật hiện tại.** Quy trình và các đường dẫn: [docs/STOCK_ANALYSIS_GEN6_SOURCE.md](docs/STOCK_ANALYSIS_GEN6_SOURCE.md).

Chính sách trên áp dụng cho **bài phân tích cổ phiếu/agent nghiên cứu**, không tự sửa công thức hoặc chuyển đổi deployment của pipeline. Các kết quả V4 cũ vẫn giữ lại để tra cứu lịch sử.


Lịch sử hệ thống V4 (chỉ tham khảo, không dùng làm tín hiệu kỹ thuật hiện tại): `v4.19-shadow`, `v4.18`, `v4.17`, `v4.9`, `v4.8`, `v4.1`, `v2.3`. `v4.18` là production của nhánh V4 legacy; `v4.19-shadow` chỉ forward-test, dùng trọng số IC cố định MeanRev/Breakout/Flow/Fund/Growth = 5/15/20/25/35 và không phát thông báo. Phương pháp và cách monitor: `docs/V419_SHADOW_WEIGHTING.md`.

## Kiểm tra dashboard

```bash
cd web
npm ci
npm run check
```

Xem `web/README.md` để chạy local và `docs/DATA_RETENTION.md` để hiểu chính sách lưu dữ liệu/cache.

## Cập nhật dashboard insight 2026-10-14

Dashboard dùng lớp snapshot phục vụ riêng cho các phép chẩn đoán nặng; workflow daily refresh snapshot sau khi đồng bộ ledger/IC và trước khi xóa cache Vercel. Header hiện tại được giữ nguyên, còn insight ưu tiên được đặt ngay dưới tiêu đề từng trang.
