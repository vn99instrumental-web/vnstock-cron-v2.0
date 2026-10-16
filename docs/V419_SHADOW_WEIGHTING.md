# v4.19 shadow: trọng số và giám sát

Cập nhật: 2026-10-15

## Mục tiêu

`v4.19-shadow` là phiên bản forward-test, không thay đổi score/decision production `v4.18` và không đi vào feed thông báo/Zalo. Shadow được materialize từ factor norm, regime gate và hold score đã có trong cùng snapshot `v4.18`, nên không gọi thêm market API.

## Công thức đang chạy

Score trade chỉ gồm năm factor lõi sau khi áp regime gate:

`100 × (5% MeanRev + 15% Breakout + 20% Flow + 25% Fund + 35% Growth)`

Context có trọng số 0; confluence và các score extra không được cộng. Trace ghi vào mỗi prediction:

- `shadow_parent_version = v4.18`
- `shadow_method = ic_shrunk_fixed_core`
- `shadow_weight_profile = mr5_bo15_flow20_fund25_growth35`
- `shadow_core_only = true`

## Cơ sở chọn trọng số

Mẫu thiết kế gồm 2.100 mã-ngày trên 21 ngày tín hiệu từ 2026-08-28 đến 2026-09-30, tối ưu cho outcome 5 phiên. IC được tính Spearman theo ngày; sau đó shrink về 0 với K=20, trừ 0,5 sai số chuẩn, áp sàn 5% và trần 35%, rồi làm tròn thành cấu hình dễ audit.

| Factor | Trọng số chạy shadow |
|---|---:|
| MeanRev | 5% |
| Breakout | 15% |
| Flow | 20% |
| Fund | 25% |
| Growth | 35% |

Trong backtest cùng mẫu, cấu hình làm tròn đạt daily IC 5d +0,222 và top-20% excess +1,44%, so với equal-weight lần lượt +0,190 và +1,07%. Đây vẫn là kết quả trong mẫu; không phải bằng chứng đủ để promote production.

## Monitor hằng ngày

- Intraday workflow tạo một ledger riêng cho `v4.19-shadow` ở mỗi lần chạy.
- Sync Supabase giữ run cuối ngày và run BUY cuối ngày của shadow để giới hạn dung lượng.
- Khi outcome 3/5/10 phiên chín, evaluator IC hiện hữu tự tính metric theo version; dashboard IC hiển thị v4.19 cùng các version khác.
- Chỉ review quyết định promote sau tối thiểu 30 ngày outcome chín độc lập. Theo dõi số ngày có outcome, cỡ mẫu, IC 3/5/10d, hit rate và mức ổn định theo thời gian; không kết luận từ một vài phiên.

Batch equal-weight đầu tiên (run `2026-10-15_13:53_v4.19-shadow`, 100 signal, chưa có outcome) đã được xóa khỏi Supabase và ledger trên `main` trước khi ghi cấu hình IC-weighted. Vì vậy chuỗi monitor giữ một phương pháp duy nhất.

## Dữ liệu lịch sử dùng cho tab Mua

Để chọn và đối chiếu v4.19 ngay trên dashboard, ledger có một lớp backfill phục vụ hiển thị từ các snapshot v4.18 trước ngày bắt đầu forward `2026-10-15`:

- Mỗi ngày chỉ giữ snapshot cuối ngày; nếu cần, giữ thêm snapshot BUY cuối ngày. Với dữ liệu hiện tại hai mốc trùng nhau, tổng cộng 2.000 row trên 20 ngày.
- Chỉ tái tính score/decision v4.19 từ factor có sẵn. Không sao chép `entry`, `stop`, `tp1`, risk/reward hoặc các mức giá giao dịch.
- Mỗi row ghi `shadow_data_origin=retrospective_backfill`, `shadow_forward_eligible=false` và ID prediction nguồn để audit.
- Evaluator outcome, IC tổng, IC ngành và forward-IC loại rõ các row hồi cứu này. Vì vậy chúng chỉ phục vụ lịch sử/đối chiếu giao diện, không làm đẹp kết quả monitor forward.
- Row sinh bởi run thật từ ngày bắt đầu forward ghi `shadow_data_origin=forward` và `shadow_forward_eligible=true`.

Script tạo lại có tính idempotent: `python scripts/backfill_v419_shadow.py --write`. Không chạy script này trong intraday; ledger lịch sử chỉ cần backfill một lần hoặc khi chủ động tái dựng.

## IC lịch sử của lớp backfill

Backfill vẫn bị loại khỏi `v4_ic_metrics` và mọi kết luận forward. Để đối chiếu factor × scoring version, exporter riêng `scripts/export_backfill_ic_to_supabase.py` nối `shadow_backfill_source_pred_id` với outcome đã chín của v4.18 rồi ghi `v4_ic_backfill_metrics`.

Tab IC ưu tiên IC forward nếu v4.19 đã đủ mẫu; trước thời điểm đó, IC lịch sử được hiển thị với nhãn `backfill lịch sử`. Hai phạm vi không bao giờ được trộn trong cùng một dòng IC.

