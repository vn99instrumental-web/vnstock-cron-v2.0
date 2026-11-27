# Ranh giới kiến trúc SSI standalone

Ngày: 2026-11-25
Trạng thái: đã triển khai; ranh giới bắt buộc cho runtime và dashboard

## Mục tiêu bất biến

Gen 6 và SSI là hai bộ tính độc lập. Hai hệ thống được phép dùng cùng dữ liệu gốc từ cùng nhà cung cấp, nhưng không được dùng kết quả tính toán của nhau.

- Nguồn thị trường chung: SSI.
- Nguồn BCTC/fundamental chung: FHSC (Finhay).
- Gen 6 sở hữu công thức, feature, score, decision và ledger Gen 6.
- SSI sở hữu công thức, feature, score, decision và ledger SSI.
- SSI phải chạy thành công khi toàn bộ artifact `output/serving/vnstock6`, `output/history/vnstock6`, cache factor Gen 6 và các module `scripts/vnstock6_*` không tồn tại.

## Được phép dùng chung

- Payload raw/immutable của SSI và FHSC.
- Metadata nguồn: endpoint, symbol, source timestamp, received timestamp, unit, fiscal period, publication/effective time khi có, raw hash và quality state.
- Lớp transport/collector có thể tái sử dụng để tránh gọi API trùng lặp, với điều kiện output nằm trong namespace trung lập và không chứa feature/ratio/score đã tính.
- Lịch giao dịch, universe và schema raw đã được kiểm chứng nếu không phụ thuộc công thức của một calculator.
- Ngoại lệ presentation-only: `/ssi/history` được phép đọc Gen 6 serving history để hiển thị symbol-date lịch sử mà SSI chưa từng tạo. Row phải giữ nguyên `calculation_engine=gen6`, version Gen 6 và nhãn vàng `Gen 6 lịch sử`; không được đổi nhãn thành SSI hoặc đi vào SSI score/outcome/IC/today/buy/analysis.

## Không được phép dùng chung

- `output/serving/vnstock6/**` hoặc `output/history/vnstock6/**` làm input cho SSI.
- `output/vnstock6/fundamental-factors.json`, `market-factors.json` hoặc cache nào chứa kết quả do Gen 6 tính.
- Các field `s_*`, factor, regime, score, decision, confidence hoặc feature kỹ thuật/BCTC đã materialize bởi Gen 6.
- Module tính toán `scripts/vnstock6_*`, `vnstock_quant.fa` của Gen 6 hoặc workflow Gen 6 như điều kiện bắt buộc để chạy SSI.
- Gắn nhãn dữ liệu “raw/shared source” cho một row đã chứa ratio, growth, cash-flow quality hoặc signal được tính sẵn.

## Ranh giới BCTC

SSI đọc trực tiếp raw BCTC FHSC và có bộ chuẩn hóa/tính toán riêng. Bộ SSI phải tự thực hiện tối thiểu:

1. Chuẩn hóa balance sheet, income statement và cash-flow theo symbol, kỳ, loại báo cáo, revision và đơn vị.
2. Chọn kỳ hiện hành/kỳ so sánh theo quy tắc point-in-time; không dùng thời điểm fetch thay cho thời điểm công bố.
3. Tính ROE, ROA, gross margin, net margin, current ratio và debt/equity theo công thức SSI.
4. Tính tăng trưởng doanh thu/lợi nhuận YoY và các trường hợp mẫu số âm/0 theo quy tắc SSI.
5. Tính CFO, cash-flow quality và ngoại lệ ngành tài chính theo quy tắc SSI.
6. Ghi `bctc_engine=ssi`, phiên bản công thức, input hash và lý do null/error vào artifact.

Gen 6 có thể tính các metric tương tự từ cùng raw payload, nhưng kết quả Gen 6 chỉ dùng để đối chiếu chẩn đoán, không làm input hoặc fallback của SSI.

## Trạng thái triển khai hiện tại

- `scripts/ssi_independent_pipeline.py` và `scripts/ssi_raw_features.py` build 17 signal, BCTC/market feature, score và decision trực tiếp từ shared raw; không import scorer, factor cache hoặc serving input Gen 6.
- Shared raw nằm trong namespace trung lập `output/shared-raw/ssi-fhsc/releases/<raw_release_id>` và được hash/verify trước khi cả hai calculator dùng.
- `.github/workflows/shared_raw_ssi_fhsc.yml` thực hiện collector, Gen 6 và SSI trong một GitHub run, nhưng ghi calculation/ledger/serving vào namespace riêng. Lỗi một calculator được ghi nhận độc lập và gate cuối báo đúng consumer thất bại.
- Dashboard `/ssi/history` có display-only Gen 6 fallback cho symbol-date SSI chưa có, thay cho backfill. SSI today/buy/analysis/outcome/IC vẫn chỉ đọc output SSI.
- Test contract kiểm tra SSI scoring không phụ thuộc Gen 6, fallback chỉ nằm ở history và provenance Gen 6 không bị đổi nhãn.

## Tiêu chí hoàn thành

SSI chỉ được đánh dấu `standalone=true` khi đồng thời thỏa các điều kiện:

- Không có import, path input hoặc workflow dependency tới `vnstock6`/Gen 6 calculator.
- Xóa/đổi tên tạm thời toàn bộ artifact Gen 6 vẫn build được SSI từ raw SSI/FHSC.
- BCTC SSI được tính từ fixture raw độc lập, có golden tests cho công thức và trường hợp ngành.
- Metadata công bố `input_layer=shared_raw`, `bctc_engine=ssi`, `gen6_dependencies=[]`.
- Backfill/forward ledger chạy lại từ raw và quality gate đạt yêu cầu đã chốt.
- Workflow SSI chạy manual/scheduled độc lập; Gen 6 thất bại không ngăn SSI nếu shared raw release hợp lệ vẫn có.

Backlog và thứ tự triển khai: [SSI_STANDALONE_PENDING_TASKS_20261125.md](SSI_STANDALONE_PENDING_TASKS_20261125.md).
