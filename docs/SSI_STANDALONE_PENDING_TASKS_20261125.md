# Pending tasks để SSI độc lập hoàn toàn với Gen 6

Ngày cập nhật: 2026-11-25
Nguồn quyết định: [SSI_STANDALONE_SOURCE_BOUNDARY_20261125.md](SSI_STANDALONE_SOURCE_BOUNDARY_20261125.md)

## Trạng thái ngắn

SSI hiện đã độc lập về công thức score và dashboard artifact, nhưng vẫn phụ thuộc Gen 6 để nhận feature đầu vào, đặc biệt là metric BCTC. Do đó chưa đạt điều kiện “SSI chạy không cần Gen 6/VNStock calculator”.

## Thứ tự triển khai bắt buộc

| Thứ tự | Task | Trạng thái | Điều kiện nghiệm thu |
|---|---|---|---|
| 0 | Khóa ranh giới kiến trúc trong `AGENTS.md`, `PROJECT_STATE.md` và tài liệu canonical | DONE 2026-11-25 | Mọi handoff ghi rõ chỉ raw SSI/FHSC được dùng chung; trạng thái hiện tại được gọi là transitional |
| 1 | Định nghĩa shared-raw contract và namespace trung lập | PENDING | Có schema/version/provenance/hash/QC cho SSI OHLCV, session/foreign và FHSC BCTC/order-book/slow data; không có ratio/feature/score tính sẵn |
| 2 | Tách collector/materializer raw khỏi runtime Gen 6 | PENDING | Một raw release có thể được tạo/đọc mà không chạy scorer hoặc feature builder Gen 6; cả hai calculator đọc cùng immutable release ID |
| 3 | Xây SSI BCTC normalizer và calculator riêng | PENDING | SSI tự tính ratio, growth, CFO/cash-flow quality từ raw FHSC; có formula version, PIT guard, sector cases và golden fixtures |
| 4 | Xây SSI market/technical/flow feature builder riêng | PENDING | 17 signal input được tạo từ raw SSI/FHSC bằng code/config SSI; null/stale semantics và provenance được giữ nguyên |
| 5 | Chuyển `ssi_independent_pipeline.py` sang SSI-owned inputs | PENDING | Không còn `GEN6_TODAY`, `GEN6_HISTORY`, path `output/**/vnstock6` hoặc field đã tính bởi Gen 6 trong input |
| 6 | Tách orchestration SSI khỏi workflow Gen 6 | PENDING | Workflow SSI chạy độc lập theo raw-release readiness/manual schedule; không dùng `workflow_run: VNStock 6 native production` |
| 7 | Backfill ledger SSI từ shared raw và so sánh bản chuyển tiếp | PENDING | Tái tạo toàn bộ ngày có raw; báo cáo khác biệt feature/score theo nguyên nhân; không lấy output cũ làm fallback |
| 8 | Thêm independence/QC/security gates | PENDING | Test fail nếu code/workflow SSI tham chiếu `vnstock6`, nếu BCTC engine khác `ssi`, raw stale/PIT sai hoặc provenance thiếu |
| 9 | Publish, deploy và xác nhận production standalone | PENDING | GitHub workflow PASS, metadata `standalone=true`, Vercel `/ssi/*` dùng release mới và smoke/visual QA PASS |

## Công việc không phải lỗi kiến trúc

- D+10 của snapshot gần nhất tiếp tục `PENDING_TIME`: phải chờ đủ 10 phiên giao dịch tương lai; không được nội suy.
- Nghiên cứu exact parity với frozen v4.18 trong repo `ssi-data-pipeline` là track kiểm chứng riêng. Nó không được dùng để lách ranh giới raw-only và không phải nguồn runtime cho SSI standalone.

## Nguyên nhân tồn tại dependency hiện tại

Lần triển khai trước tối ưu tốc độ bằng cách tái sử dụng row feature đã materialize cho Gen 6. Cách đó tránh gọi lại SSI/FHSC và vẫn tách scorer, nhưng đã gộp hai khái niệm khác nhau:

- dùng chung **nguồn/raw data** là đúng;
- dùng chung **feature/BCTC đã tính** là không đúng với mục tiêu standalone.

Việc sửa phải tách lớp raw ở trước hai calculator, thay vì nhân đôi API call hoặc cho SSI tiếp tục đọc artifact Gen 6.
