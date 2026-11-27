# Pending tasks để SSI độc lập hoàn toàn với Gen 6

Ngày cập nhật: 2026-11-27
Nguồn quyết định: [SSI_STANDALONE_SOURCE_BOUNDARY_20261125.md](SSI_STANDALONE_SOURCE_BOUNDARY_20261125.md)

## Trạng thái ngắn

Code SSI hiện đã độc lập về công thức score, feature đầu vào, BCTC calculator, workflow và dashboard artifact. SSI chỉ đọc immutable raw release từ SSI/FHSC, không đọc Gen 6 hoặc `vnstock_quant.fa`; chưa thể tuyên bố full-data production vì workflow mới chưa được merge/chạy với credential thật và chưa có live raw release/backfill.

## Thứ tự triển khai bắt buộc

| Thứ tự | Task | Trạng thái | Điều kiện nghiệm thu |
|---|---|---|---|
| 0 | Khóa ranh giới kiến trúc trong `AGENTS.md`, `PROJECT_STATE.md` và tài liệu canonical | DONE 2026-11-25 | Mọi handoff ghi rõ chỉ raw SSI/FHSC được dùng chung; trạng thái hiện tại được gọi là transitional |
| 0A | Đồng bộ visual Gen 6/SSI và highlight dữ liệu thiếu | DONE 2026-11-25 | Các route SSI dùng chung shell/component Gen 6; giá trị `null` hiển thị màu vàng, không đổi 0 thành missing; adapter/chart SSI không fallback sang serving Gen 6 |
| 1 | Định nghĩa shared-raw contract và namespace trung lập | DONE LOCAL 2026-11-25 | Có schema/version/provenance/hash/QC cho SSI OHLCV, session/foreign và FHSC BCTC/order-book/slow data; không có ratio/feature/score tính sẵn |
| 2 | Tách collector/materializer raw khỏi runtime Gen 6 | IN PROGRESS | Collector/workflow trung lập đã độc lập và SSI đọc release ID; Gen 6 chưa chuyển transport sang cùng release ID |
| 3 | Xây SSI BCTC normalizer và calculator riêng | DONE LOCAL 2026-11-25 | SSI tự tính ratio, growth, CFO/cash-flow quality từ raw FHSC; có formula version, PIT guard, sector cases và golden fixtures |
| 4 | Xây SSI market/technical/flow feature builder riêng | DONE LOCAL 2026-11-25 | 17 signal input được tạo từ raw SSI/FHSC bằng code/config SSI; null/stale semantics và provenance được giữ nguyên |
| 5 | Chuyển `ssi_independent_pipeline.py` sang SSI-owned inputs | DONE LOCAL 2026-11-25 | Không còn `GEN6_TODAY`, `GEN6_HISTORY`, path `output/**/vnstock6` hoặc field đã tính bởi Gen 6 trong input |
| 6 | Tách orchestration SSI khỏi workflow Gen 6 | DONE LOCAL 2026-11-25 | Workflow SSI chạy theo shared-raw readiness/manual dispatch; không còn chờ workflow Gen 6 |
| 7 | Backfill ledger SSI từ shared raw và so sánh bản chuyển tiếp | PENDING LIVE RAW | Cần publish raw release thật đầu tiên và tích lũy/cấp raw lịch sử; không dùng output cũ làm fallback |
| 8 | Thêm independence/QC/security gates | DONE LOCAL 2026-11-25 | Unit/golden/tamper/boundary tests pass; GitHub run trên raw thật vẫn phải xác nhận |
| 9 | Publish, deploy và xác nhận production standalone | IN PROGRESS REMOTE | Code đã push và Vercel đã deploy/smoke auth gate; còn merge/publish workflow, tạo raw release thật, build/backfill SSI artifact, chạy GitHub gates và visual QA sau đăng nhập |

## Trạng thái triển khai raw ngày 2026-11-25

- Contract: `docs/SHARED_RAW_SSI_FHSC_CONTRACT.md`; namespace `output/shared-raw/ssi-fhsc`.
- Collector/validator: `scripts/shared_raw_collector.py`; workflow độc lập `.github/workflows/shared_raw_ssi_fhsc.yml`.
- SSI-owned calculations: `scripts/ssi_raw_features.py`; pipeline score không còn đọc path/artifact Gen 6.
- Workflow SSI chỉ chờ `Shared raw SSI FHSC production` và chạy `scripts/validate_ssi_standalone.py` trước build.
- Commit `8f80df1256bdf9e22208ebd0b5da54893d1711c4` đã push lên `codex/ssi-gen6-parallel-tabs`.
- Vercel production `dpl_AbyvGSYzqT5LHxQMTDGXSSgjbF34` READY; alias production và auth-gate smoke check PASS. Commit mới chỉ đổi pipeline/docs nên Vercel Git integration bỏ preview build theo đúng Ignored Build Step; production được build thủ công từ repo root.
- 15 focused tests pass locally. Chưa có raw release live trong repo này, nên backfill và production standalone data chưa được xác nhận.

## Công việc không phải lỗi kiến trúc

- D+10 của snapshot gần nhất tiếp tục `PENDING_TIME`: phải chờ đủ 10 phiên giao dịch tương lai; không được nội suy.
- Nghiên cứu exact parity với frozen v4.18 trong repo `ssi-data-pipeline` là track kiểm chứng riêng. Nó không được dùng để lách ranh giới raw-only và không phải nguồn runtime cho SSI standalone.

## Nguyên nhân tồn tại dependency hiện tại

Lần triển khai trước tối ưu tốc độ bằng cách tái sử dụng row feature đã materialize cho Gen 6. Cách đó tránh gọi lại SSI/FHSC và vẫn tách scorer, nhưng đã gộp hai khái niệm khác nhau:

- dùng chung **nguồn/raw data** là đúng;
- dùng chung **feature/BCTC đã tính** là không đúng với mục tiêu standalone.

Việc sửa phải tách lớp raw ở trước hai calculator, thay vì nhân đôi API call hoặc cho SSI tiếp tục đọc artifact Gen 6.
