# Quy trình Calibrate hàng tháng

Manual trigger. Chỉ report — KHÔNG tự đổi scoring. Bạn review rồi sửa tay.

## Mỗi tháng chạy 3 lần (thứ tự)

### 1. Build dataset mới
```
mode=full, horizon=5
```
Fetch dữ liệu mới nhất (~3 phút), tính lại TA + v1/v2 score + forward returns.
Output: so sánh V1 vs V2 + V2 hit_avg theo tháng.

### 2. Audit từng indicator
```
mode=audit, horizon=all
```
Dùng dataset vừa build. Đo lại từng indicator (threshold/correlation/quintile)
cho cả 3 horizon. Cho biết indicator nào còn predictive, cái nào nên đảo dấu.

### 3. Drift detection
```
mode=drift, horizon=5
```
So edge hiện tại với các lần chạy trước (lưu trong drift_history.json).
Phát hiện khi logic mean-reversion bắt đầu suy yếu.

## Đọc kết quả — 3 tín hiệu cảnh báo

| Tín hiệu | Ý nghĩa | Hành động |
|---|---|---|
| `V2 hit_recent30d < 0.50` | Logic đang thua random gần đây | Re-audit, cân nhắc đảo lại dấu |
| `Indicator ⚠️ ĐẢO DẤU` | Chế độ thị trường đã đổi | Đảo dấu indicator đó trong step_scoring |
| `V2 hit giảm dần qua nhiều kỳ` | Drift thật (không phải nhiễu) | Calibrate lại toàn bộ |

## Khi cần đổi scoring (sửa tay)

Nếu report cho thấy indicator nào đó đã đảo dấu hoặc suy yếu:

1. Mở `steps/step_scoring.py`
2. Tìm indicator tương ứng (vd CMF, MFI, EMA200)
3. Đảo dấu / điều chỉnh theo bằng chứng mới
4. Cập nhật comment `Phase 2.xx calibrated: <ngày>`
5. Commit → chạy `mode=full` để xác nhận hit_avg cải thiện
6. Theo dõi 1-2 tuần trước khi tin tưởng

## Lưu ý quan trọng

**Logic hiện tại là HỖN HỢP** — EMA200/CMF/RSI/BB theo mean-reversion,
nhưng EMA cross/Supertrend/MACD vẫn trend-following (chưa đụng vì bằng chứng
yếu). Chúng một phần triệt tiêu nhau → đó là lý do hit_avg chỉ 0.55.

**Dư địa cải thiện lần sau:** nếu drift detection xác nhận mean-reversion
ổn định qua 2-3 tháng, có thể cân nhắc đảo nốt EMA cross + giảm Supertrend
để logic nhất quán → có thể đẩy hit_avg cao hơn.

**Rủi ro regime change:** logic nghiêng mean-reversion. Nếu thị trường vào
uptrend mạnh kéo dài, drift detection sẽ báo `ĐẢO DẤU` cho price_vs_ema200 —
đó là lúc cân nhắc chuyển một phần về trend-following.
