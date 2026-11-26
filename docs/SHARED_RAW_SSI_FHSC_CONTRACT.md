# Shared raw SSI/FHSC contract

Ngày hiệu lực: 2026-11-25
Schema: `shared-raw-release-v1`

## Mục đích

Collector này là lớp dùng chung duy nhất giữa Gen 6 và SSI. Nó chỉ lưu payload nguyên bản từ SSI/FHSC cùng metadata vận chuyển; không tính ratio, indicator, feature, signal, score hay decision. Hai calculator phải đọc cùng một `release_id` nhưng tự chuẩn hóa và tính toán độc lập.

## Namespace và tính bất biến

- Pointer: `output/shared-raw/ssi-fhsc/current.json`.
- Release: `output/shared-raw/ssi-fhsc/releases/<release_id>/`.
- `release_id` có dạng `YYYYMMDDTHHMMSSZ-<8 hex>`.
- Release đã tồn tại không được ghi đè. Pointer chỉ được publish sau khi coverage gate, manifest và toàn bộ SHA-256 pass.
- Schema kiểm chứng: `schemas/shared_raw_release.schema.json`.

## Dataset

Mỗi dòng JSONL là một envelope gồm `source`, `endpoint`, `symbol`, `parameters`, `fetched_at`, `status`, `row_count`, `raw_sha256`, `rows` và lỗi đã loại bỏ message nhạy cảm. `rows` giữ các cột provider gửi về, gồm cả `columns="all"`.

Nguồn được phép:

- SSI: reference, VNINDEX/equity OHLCV, foreign flow, session stats.
- FHSC: balance sheet, income statement, cash flow, order book; proprietary flow và insider deal chỉ ở mode `full` hậu kiểm sau phiên.

Mode `market` không gọi ba endpoint FHSC chậm là order book, proprietary flow và insider deal. Mode `full` dùng cho post-market release hoàn chỉnh.

## Quality gate

- Ít nhất 80 mã có OHLCV thành công (hoặc toàn bộ universe nếu universe nhỏ hơn 80).
- VNINDEX OHLCV phải thành công.
- Mọi dataset và payload envelope phải khớp SHA-256.
- `contract.calculated_fields` bắt buộc là mảng rỗng và `gen6_dependency=false`.

Endpoint có thể trả empty/error mà không bị biến thành 0. Consumer phải giữ null và provenance tương ứng; không được fallback sang artifact đã tính của Gen 6 hoặc SSI.

## CLI

```bash
~/.venv_6x/bin/python scripts/shared_raw_collector.py collect --mode full
~/.venv_6x/bin/python scripts/shared_raw_collector.py verify
```

Workflow độc lập: `.github/workflows/shared_raw_ssi_fhsc.yml`. Workflow này không gọi scorer/feature builder Gen 6.
