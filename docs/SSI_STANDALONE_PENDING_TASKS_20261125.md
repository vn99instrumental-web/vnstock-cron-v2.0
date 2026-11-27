# Pending tasks để SSI có full data và độc lập với Gen 6

Ngày cập nhật: 2026-11-27

## Quy tắc kiến trúc

Gen 6 và SSI là hai calculator độc lập. Cả hai dùng cùng immutable provider raw từ SSI/FHSC và cùng `raw_release_id`, nhưng không dùng chung ratio, feature, signal, score, decision hoặc BCTC đã tính:

- Gen 6: `scripts/vnstock6_raw_adapter.py` -> `vnstock_quant.fa` -> scoring/profile Gen 6.
- SSI: `scripts/ssi_raw_features.py` -> BCTC/market formulas SSI -> scoring SSI.

Quy tắc vận hành bắt buộc là **collect once, calculate many**:

- Mỗi cadence chỉ publish một immutable `raw_release_id`.
- Gen 6 và SSI phải nhận cùng ID này.
- Retry calculator, sửa formula hoặc build lại dashboard phải tái sử dụng release đã có; không được gọi lại SSI/FHSC chỉ để tính lại.
- Chỉ collector theo cadence mới được tạo release mới. Consumer không có quyền tự dispatch collector.

## Task full data 1-5

| # | Task | Trạng thái | Bằng chứng/điều kiện hoàn tất |
|---|---|---|---|
| 1 | Publish contract/workflow trung lập lên `main` | DONE | Commit `3b0b105f3`; collector có cadence `intraday/daily/weekly`, hash, QC và release bất biến |
| 2 | Chuyển Gen 6 sang cùng raw release nhưng giữ calculator riêng | DONE | Adapter raw, `fundamental_factors_from_frames`, provenance `raw_release_id`; unit test chứng minh gọi `vnstock_quant.fa`, không gọi SSI calculator |
| 3 | Chạy release live đầy đủ và đo coverage | DONE | Collector run `45938422349` publish release `20261127T041229Z-d12e27b5`; manifest, hash và raw QC PASS |
| 4 | Build/publish SSI và Gen 6 từ cùng release, chạy gates và revalidate Vercel | DONE | Gen 6 run `45949217456`; SSI calculator-only run `45952046277`; cả hai success, serving metadata cùng release ID, Vercel revalidate đã chạy |
| 5 | Chuyển lịch n8n intraday/daily/weekly | DONE LIVE | Workflow `Unified SSI FHSC data cadence` (`RPjryobbCgj9dcOLM`) đã publish với GitHub API credential; legacy daily/intraday/weekly và backup đều unpublished. Daily run `45962958727` collect một release `20261127T080622Z-bd6870bd`, sau đó Gen 6/SSI tính tuần tự, publish riêng và revalidate thành công. |

## Coverage live của release chung

| Dataset/feature | Coverage | Ý nghĩa phần thiếu |
|---|---:|---|
| OHLCV SSI | 100/100 | Đủ |
| Foreign SSI | 100/100 | Đủ |
| Foreign FHSC | 100/100 | Đủ |
| Session stats SSI | 0/100 | Provider trả empty; giữ null |
| Active session FHSC | 99/100 | VCB lỗi mạng trong lần collect |
| Balance sheet FHSC | 99/100 | VNM lỗi mạng |
| Income statement FHSC | 96/100 | PNJ, POW, PVD, VIC lỗi mạng |
| Cash flow FHSC | 90/100 | 10 mã lỗi mạng; không lấy BCTC Gen 6 để bù |
| Proprietary flow FHSC | 99/100 | VIB lỗi mạng |
| Insider FHSC | 74/100 | 26 mã trả empty |
| Order book FHSC | 100/100 | Đủ |

SSI sau khi tính độc lập: 100/100 mã có score; `of_phasefix` 100, `ff_net` 99, `prop_5d` 99, `growth_core` 96, `cf_core` 90, `depth_wall` 84 và `insider` 64. Có 46 mã đủ cả 17 signal; mọi mã đạt tối thiểu 14 signal.

## Coverage không thể bịa

Dữ liệu provider trả empty/error phải giữ null và được dashboard highlight vàng. “Full data” nghĩa là đã thu đủ các endpoint được phép theo cadence và công khai coverage thật; không được điền 0 hoặc lấy artifact calculator còn lại làm input tính toán.

Riêng lịch sử trước khi SSI có snapshot không cần backfill: `/ssi/history` hiển thị row Gen 6 cùng symbol-date với nhãn vàng `Gen 6 lịch sử` và provenance Gen 6. Đây là fallback hiển thị, không phải SSI data và không tham gia score, outcome hoặc IC của SSI.

D+10/outcome mới vẫn phụ thuộc số phiên tương lai thực tế. Đây là `PENDING_TIME`, không phải lỗi collector hoặc dependency Gen 6.

## Pending còn lại

Không còn task code/runtime hay n8n activation nào trong nhóm full-data 1-5. Việc còn lại không được giải quyết bằng cách rerun collector:

1. `PENDING_TIME`: tích lũy outcome D+10 theo phiên giao dịch thực tế và các snapshot lịch sử mới.

## Kiểm thử

- Baseline full suite: 104/104 PASS trước compatibility wrapper.
- Full suite 114/114 PASS; contract mới gồm 5 n8n/unified-run, 7 collector/cadence và 3 dashboard history fallback. Calculator-only run `45959083307` PASS từ raw release có sẵn, không recollect. Live daily run `45962958727` PASS: collect một release, Gen 6/SSI dùng cùng ID, publish hai namespace và revalidate một lần.
- `validate_ssi_standalone` package mode: PASS.
- Security review: không commit token/secret; `raw_release_id` được regex validate; n8n JSON không chứa credential value.
