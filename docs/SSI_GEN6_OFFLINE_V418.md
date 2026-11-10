# Gen6: đối chiếu dữ liệu SSI v4.18 offline trên trading-web

## Phạm vi
Chỉ cập nhật web `/vnstock6` (lựa chọn **Thế hệ 6** ở menu nguồn), không thay đổi tab Mua/Hôm nay, không sửa thuật toán VNStock v4.18/v4.19, không thay nguồn GitHub serving hiện tại, không tự gửi Zalo.

Nguồn: [SSI repo audited artifact](https://github.com/vn99instrumental-web/ssi-data-pipeline/blob/main/output/audit/ssi_v418_offline_gen6_export.json). Copy nguyên JSON được tạo bằng script `src/ssi_pipeline/v418_offline_gen6_export.py` sau [PR SSI #17](https://github.com/vn99instrumental-web/ssi-data-pipeline/pull/17). Đích tĩnh: `web/data/ssi-v418-offline-source.json` trong repo VNStock. `web/lib/ssi-v418-offline.ts` kiểm cấu trúc, số mã, số tín hiệu và khóa NOT_FOR_TRADING trước khi render. Giao diện: `web/components/ssi-offline-comparison.tsx`.

## Nguồn và ngày
- SSI market sample **09/11/2026**: **97 mã**, OHLC + matched value 97/97, khối ngoại 96/97; 95/97 đủ 252 phiên, 93/97 đủ 400 phiên.
- SSI VNINDEX **69** finalized source days, VN100 stage **100 × 21 = 2.100** bars; không chứng nhận danh sách thành viên theo ngày lịch sử.
- Finhay trực tiếp PE/PB 10/10, báo cáo tài chính có publication PIT **0/10**.
- **17/17** source-field schema mapped, **0/17** signal values được chứng nhận tương đương. `score_trade_ssi=null`, `decision_ssi=null`, `score_comparable=false`.
- Giá là **SSI as reported**, không dùng giá điều chỉnh lại quá khứ theo quyết định chủ dự án. Chưa xác nhận SSI có điều chỉnh trước khi trả API hay không. Tuyệt đối không ghép với VCI khác thời điểm để tính độ lệch/độ chính xác.

## Cách kiểm thử và đồng bộ lần sau
1. Ở repo SSI, chạy offline `v418_offline_gen6_export`; kiểm `NOT_FOR_TRADING`, `release_gate_status=BLOCKED_INPUT`, nguồn `cohort_trade_date`.
2. Thay *toàn bộ* JSON trong `web/data/ssi-v418-offline-source.json` bằng artifact gốc sau nghiệm thu; không tái tạo từ scoreboard/các con số tự nhập.
3. Tại repo VNStock, chạy `cd web && npm ci && npm run check`.
4. Triển khai vào **trading-web** Vercel từ commit đã kiểm tra và xác nhận `/vnstock6` hiển thị đúng nguồn/ngày. Nếu Vercel build CANCELED/ERROR thì việc merge GitHub **chưa được coi là deploy thành công**.

## Giới hạn
Snapshot là **tĩnh**, phải đồng bộ lại sau các lượt dữ liệu mới. Tích hợp native SSI+Finhay scoring, full-session trade tape, CFO/D/E/PIT, historic VN100 membership, exact v4.18 parity và forward ledger vẫn pending. Các tab còn lại của Thế hệ 6 đang dùng Gen6 bridge cũ, **không tự chuyển sang SSI scores**.
