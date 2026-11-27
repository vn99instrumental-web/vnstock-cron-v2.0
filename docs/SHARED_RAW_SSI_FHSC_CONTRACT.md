# Shared raw SSI/FHSC contract

Ngày hiệu lực: 2026-11-27
Schema: `shared-raw-release-v1`

## Mục đích

Đây là lớp dùng chung duy nhất giữa Gen 6 và SSI. Collector chỉ lưu payload nguyên bản từ SSI/FHSC cùng metadata vận chuyển; không tính ratio, indicator, feature, signal, score hay decision. Hai calculator đọc cùng một `release_id` nhưng tự chuẩn hóa và tính toán độc lập:

- Gen 6 dùng `vnstock_quant.fa` và các profile Gen 6.
- SSI dùng normalizer, BCTC calculator và scoring riêng của SSI; không import `vnstock_quant.fa` hay artifact Gen 6.

## Namespace và tính bất biến

- Pointer: `output/shared-raw/ssi-fhsc/current.json`.
- Release: `output/shared-raw/ssi-fhsc/releases/<release_id>/`.
- `release_id`: `YYYYMMDDTHHMMSSZ-<8 hex>`.
- Release đã tồn tại không được ghi đè. Pointer chỉ publish sau khi coverage, manifest và toàn bộ SHA-256 pass.
- Schema: `schemas/shared_raw_release.schema.json`.
- Mỗi consumer bắt buộc nhận đúng `raw_release_id`; không được tự suy ra release mới nhất trong lúc chạy production.

## Cadence và dataset

Mỗi dòng JSONL là một envelope gồm `source`, `endpoint`, `symbol`, `parameters`, `fetched_at`, `status`, `row_count`, `raw_sha256`, `rows` và lỗi đã loại message nhạy cảm. `rows` giữ nguyên các cột provider trả về. Ba dataset BCTC được lưu dưới dạng deterministic gzip (`*.jsonl.gz`) để giữ nguyên toàn bộ provider rows mà vẫn nằm dưới giới hạn blob của GitHub; hash trong manifest áp dụng trên bytes đã nén và verifier giải nén trước khi kiểm tra envelope.

| Cadence | SSI | FHSC | Không gọi |
|---|---|---|---|
| `intraday` | reference, VNINDEX/equity daily OHLCV, 5m OHLCV, foreign flow, session stats | foreign fallback, active-session fallback, order book | BCTC, proprietary, insider |
| `daily` | reference, VNINDEX/equity daily OHLCV, foreign flow, session stats | foreign/active-session fallback, 3 BCTC statements, proprietary, insider | intraday 5m, order book mới |
| `weekly` | reference, VNINDEX/equity daily OHLCV, foreign flow, session stats | foreign/active-session fallback, 3 BCTC statements, proprietary, insider, order book | intraday 5m |

SSI có thể dùng dataset chậm từ raw release gần nhất trước đó khi cadence hiện tại cố ý không thu endpoint đó. Gen 6 dùng cache đã tính của chính Gen 6 cho cùng mục đích. Không consumer nào được fallback sang artifact đã tính của calculator còn lại.

## Quality gate

- Ít nhất 80 mã có daily OHLCV thành công, hoặc toàn bộ universe nếu nhỏ hơn 80.
- VNINDEX OHLCV phải thành công.
- Mọi dataset và payload envelope phải khớp SHA-256.
- `cadence` phải là `intraday`, `daily` hoặc `weekly`.
- `contract.calculated_fields=[]` và `gen6_dependency=false`.
- Empty/error giữ nguyên null và provenance; không đổi thành 0.

## CLI và orchestration

```bash
~/.venv_6x/bin/python scripts/shared_raw_collector.py collect --cadence intraday
~/.venv_6x/bin/python scripts/shared_raw_collector.py collect --cadence daily
~/.venv_6x/bin/python scripts/shared_raw_collector.py collect --cadence weekly
~/.venv_6x/bin/python scripts/shared_raw_collector.py verify
```

n8n chỉ dispatch `.github/workflows/shared_raw_ssi_fhsc.yml`. Workflow collector publish raw rồi fan-out cùng một `raw_release_id` sang SSI và workflow Gen 6 tương ứng. File import n8n canonical: `n8n/shared-raw-ssi-fhsc-schedule.json`.
