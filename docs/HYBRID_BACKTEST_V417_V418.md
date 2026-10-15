# Backtest hybrid factor v4.17/v4.18

**Tạo lúc:** 2026-10-15 01:33 UTC
**Dữ liệu:** 2026-08-28 → 2026-09-30; 21 ngày tín hiệu; 2,100 mã-ngày đã join outcome.

## Candidate được kiểm định

- Mean Reversion và Flow: chọn từ v4.17.
- Breakout, Fundamental và Growth: chọn từ v4.18.
- Kiểm tra source cho thấy v4.18 chỉ đổi trọng số TRADE so với v4.17; công thức/cap của 5 factor không đổi. Vì vậy lựa chọn source không tạo giá trị factor mới. Candidate có thể kiểm định là cách ghép trọng số.
- `hybrid_equal`: 20% cho mỗi factor; score dùng factor norm × regime gate, không dùng bonus/extras.
- Sensitivity `hybrid_no_mr`: MR=0%, bốn factor còn lại 25%; đây là chẩn đoán sau khi xem dữ liệu, không phải candidate đăng ký trước.

Đối chứng: trọng số production v4.17 và v4.18 được áp lại trên cùng toàn bộ quan sát.

## Kết quả

### Toàn kỳ

Khoảng ngày: 2026-08-28 → 2026-09-30 (21 ngày).

| Horizon | Model | Daily IC | 95% CI IC | Top 20% return | Market | Excess | 95% CI excess | Hit rate | n |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 3d | v4.17 | +0.078 | [+0.037, +0.121] | -0.49% | -0.84% | +0.35% | [+0.02, +0.67]% | 38.8% | 2,100 |
| 3d | v4.18 | -0.024 | [-0.088, +0.042] | -1.24% | -0.84% | -0.40% | [-0.75, -0.07]% | 31.7% | 2,100 |
| 3d | hybrid_equal | +0.119 | [+0.075, +0.163] | -0.27% | -0.84% | +0.57% | [+0.29, +0.86]% | 41.0% | 2,100 |
| 3d | hybrid_no_mr | +0.157 | [+0.093, +0.218] | -0.01% | -0.84% | +0.83% | [+0.43, +1.24]% | 42.1% | 2,100 |
| 5d | v4.17 | +0.135 | [+0.097, +0.175] | -0.61% | -1.27% | +0.66% | [+0.25, +1.06]% | 39.3% | 2,100 |
| 5d | v4.18 | -0.013 | [-0.069, +0.048] | -1.77% | -1.27% | -0.50% | [-0.96, -0.07]% | 30.0% | 2,100 |
| 5d | hybrid_equal | +0.190 | [+0.156, +0.224] | -0.20% | -1.27% | +1.07% | [+0.77, +1.38]% | 45.0% | 2,100 |
| 5d | hybrid_no_mr | +0.231 | [+0.185, +0.276] | +0.25% | -1.27% | +1.53% | [+1.16, +1.91]% | 47.9% | 2,100 |
| 10d | v4.17 | +0.197 | [+0.149, +0.241] | -1.12% | -2.25% | +1.13% | [+0.48, +1.75]% | 39.3% | 2,100 |
| 10d | v4.18 | +0.023 | [-0.018, +0.060] | -2.51% | -2.25% | -0.26% | [-0.98, +0.43]% | 32.9% | 2,100 |
| 10d | hybrid_equal | +0.259 | [+0.210, +0.300] | -0.14% | -2.25% | +2.11% | [+1.67, +2.52]% | 46.2% | 2,100 |
| 10d | hybrid_no_mr | +0.295 | [+0.255, +0.331] | +0.65% | -2.25% | +2.90% | [+2.38, +3.46]% | 50.7% | 2,100 |

### 30% ngày mới nhất (pseudo-OOS)

Khoảng ngày: 2026-09-22 → 2026-09-30 (7 ngày).

| Horizon | Model | Daily IC | 95% CI IC | Top 20% return | Market | Excess | 95% CI excess | Hit rate | n |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 3d | v4.17 | +0.027 | [-0.036, +0.080] | -1.46% | -1.41% | -0.05% | [-0.70, +0.71]% | 30.7% | 700 |
| 3d | v4.18 | -0.110 | [-0.211, -0.025] | -2.62% | -1.41% | -1.21% | [-1.69, -0.73]% | 18.6% | 700 |
| 3d | hybrid_equal | +0.111 | [+0.047, +0.179] | -1.03% | -1.41% | +0.38% | [+0.01, +0.85]% | 32.1% | 700 |
| 3d | hybrid_no_mr | +0.203 | [+0.127, +0.278] | -0.27% | -1.41% | +1.14% | [+0.59, +1.78]% | 42.1% | 700 |
| 5d | v4.17 | +0.070 | [+0.037, +0.114] | -1.76% | -2.01% | +0.24% | [-0.63, +1.18]% | 27.9% | 700 |
| 5d | v4.18 | -0.121 | [-0.168, -0.076] | -3.62% | -2.01% | -1.62% | [-2.30, -0.93]% | 18.6% | 700 |
| 5d | hybrid_equal | +0.157 | [+0.106, +0.211] | -1.42% | -2.01% | +0.58% | [+0.22, +0.91]% | 30.0% | 700 |
| 5d | hybrid_no_mr | +0.265 | [+0.209, +0.314] | -0.18% | -2.01% | +1.82% | [+1.25, +2.41]% | 42.1% | 700 |
| 10d | v4.17 | +0.112 | [+0.037, +0.188] | -2.94% | -3.26% | +0.33% | [-1.03, +1.85]% | 30.7% | 700 |
| 10d | v4.18 | -0.066 | [-0.123, -0.010] | -5.35% | -3.26% | -2.09% | [-2.94, -1.11]% | 24.3% | 700 |
| 10d | hybrid_equal | +0.173 | [+0.081, +0.260] | -2.18% | -3.26% | +1.08% | [+0.55, +1.54]% | 36.4% | 700 |
| 10d | hybrid_no_mr | +0.264 | [+0.176, +0.348] | -0.07% | -3.26% | +3.20% | [+1.83, +4.61]% | 47.9% | 700 |

## Chẩn đoán từng factor

Daily IC của từng factor sau regime gate, tính trên cùng cửa sổ pooled. Bảng này giúp phân biệt hiệu quả do ghép trọng số với hiệu quả do tên version.

| Horizon | Factor | IC toàn kỳ | 95% CI | IC 30% ngày mới nhất | 95% CI |
|---:|---|---:|---:|---:|---:|
| 3d | mean_reversion | -0.115 | [-0.192, -0.033] | -0.199 | [-0.301, -0.107] |
| 3d | breakout | +0.060 | [-0.008, +0.125] | +0.126 | [+0.055, +0.206] |
| 3d | flow | +0.067 | [-0.000, +0.136] | -0.027 | [-0.076, +0.028] |
| 3d | fundamental | +0.087 | [+0.034, +0.142] | +0.155 | [+0.062, +0.247] |
| 3d | growth | +0.101 | [+0.054, +0.150] | +0.142 | [+0.057, +0.243] |
| 5d | mean_reversion | -0.144 | [-0.210, -0.069] | -0.248 | [-0.304, -0.180] |
| 5d | breakout | +0.072 | [+0.004, +0.132] | +0.112 | [+0.053, +0.156] |
| 5d | flow | +0.114 | [+0.056, +0.178] | +0.038 | [-0.021, +0.102] |
| 5d | fundamental | +0.130 | [+0.085, +0.177] | +0.220 | [+0.153, +0.292] |
| 5d | growth | +0.154 | [+0.123, +0.185] | +0.173 | [+0.121, +0.219] |
| 10d | mean_reversion | -0.147 | [-0.185, -0.109] | -0.206 | [-0.279, -0.137] |
| 10d | breakout | +0.078 | [+0.032, +0.124] | +0.094 | [+0.026, +0.166] |
| 10d | flow | +0.127 | [+0.076, +0.176] | +0.045 | [-0.031, +0.126] |
| 10d | fundamental | +0.197 | [+0.162, +0.234] | +0.265 | [+0.245, +0.288] |
| 10d | growth | +0.179 | [+0.141, +0.210] | +0.133 | [+0.050, +0.211] |

## Kiểm tra tái dựng score

Score đối chứng được tái dựng từ factor norm × gate × weight. Ledger score thật còn có confluence/flow extras, nên MAE không bằng 0; daily rank correlation cần ở mức rất cao.

| Version | Số ngày | Daily rank correlation với score thật | MAE score |
|---|---:|---:|---:|
| v4.17 | 11 | 0.9739 | 2.11 |
| v4.18 | 10 | 0.9832 | 2.22 |

## Kết luận

- `hybrid_equal` vượt hai đối chứng production ở 5d: IC +0.190 và excess +1.07% toàn kỳ; ở 30% ngày mới nhất là IC +0.157 và excess +0.58%.
- Candidate thắng về xếp hạng tương đối nhưng top 20% vẫn có return âm trong giai đoạn thị trường giảm. Không nên diễn giải đây là chiến lược tạo lợi nhuận tuyệt đối.
- `hybrid_no_mr` chỉ là sensitivity được hình thành sau khi nhìn kết quả, nên có selection bias và không được dùng để tuyên bố thắng ngoài mẫu.
- Kết quả ủng hộ chạy shadow `hybrid_equal`; chưa đủ bằng chứng để thay production trước khi có ít nhất 30 ngày outcome chín độc lập.

## Cách đọc và giới hạn

- IC là Spearman theo từng ngày rồi mới lấy trung bình; CI bootstrap theo ngày, tránh coi các mã trong cùng ngày là độc lập.
- Top 20% là danh mục xếp hạng cao nhất mỗi ngày. Return và excess là trung bình đều theo ngày, chưa trừ phí.
- `pseudo-OOS` chỉ là đoạn thời gian mới nhất, không phải out-of-sample hoàn toàn vì ý tưởng chọn factor xuất phát từ IC đã quan sát.
- Số ngày còn ngắn; không dùng kết quả này để tự động thay production. Candidate chỉ nên chạy shadow cho tới khi có ít nhất 30 ngày chín độc lập.
- Ledger giữ Flow và fundamental tại thời điểm tín hiệu; đây là lợi thế so với replay OHLC bị trung hòa Flow hoặc dùng fundamental hiện tại.

## Truy xuất nguồn

- v4.17: 1,100 mã-ngày.
- v4.18: 1,000 mã-ngày.
- Predictions: `output/history/v2f_predictions_v4/*.jsonl`.
- Outcomes: `output/history/v2f_outcomes_v4/*.jsonl`.
- Script: `backtest/backtest_hybrid_v417_v418.py`.
## Quyết định vận hành v4.19-shadow (2026-10-15)

`hybrid_equal` trong báo cáo trên được giữ như benchmark lịch sử, không còn là công thức shadow đang chạy. Batch equal-weight đầu tiên chưa có outcome đã được xóa khỏi Supabase; candidate vận hành được chốt thành trọng số IC cố định MeanRev/Breakout/Flow/Fund/Growth = 5/15/20/25/35.

Trên cùng mẫu 21 ngày/2.100 mã-ngày ở horizon 5d, cấu hình làm tròn đạt daily IC +0,222 và top-20% excess +1,44%; equal-weight đạt +0,190 và +1,07%. Trọng số được tạo bằng IC theo ngày có shrinkage K=20, penalty 0,5 SE, sàn 5% và trần 35%. Vì vẫn là lựa chọn dựa trên cùng mẫu, v4.19 tiếp tục ở trạng thái shadow và cần tối thiểu 30 ngày outcome chín độc lập trước khi đánh giá promote. Chi tiết: `docs/V419_SHADOW_WEIGHTING.md`.
