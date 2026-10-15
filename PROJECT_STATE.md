# PROJECT_STATE.md

**Cập nhật:** 2026-10-14
**Branch production:** `main`
**Dashboard:** <https://trading-snapshot-dl.vercel.app>

## Tóm tắt

Ứng dụng production gồm pipeline Python, ledger lưu trong Git, Supabase làm lớp dữ liệu phục vụ dashboard và Next.js deploy trên Vercel. Scoring formula không thuộc phạm vi thay đổi UI/data-serving hiện tại.

## Stack và kiến trúc

- Python pipeline/workflows tạo ledger và dữ liệu đánh giá.
- Git/GitHub là nguồn lịch sử có thể backfill.
- Supabase project `mcaqnaomzoqgxccdgvls` chứa dữ liệu dashboard; project đang dùng chung với ứng dụng khác.
- Next.js App Router trong `web/`, Supabase Auth bảo vệ khu vực owner.
- Vercel deploy từ `main`; `web/vercel.json` đặt Functions tại `hnd1`.

## Scoring version được review

Theo thứ tự mới nhất: `v4.18`, `v4.17`, `v4.9`, `v4.8`, `v4.1`, `v2.3`.

Các tab Buy, Hôm nay, Lịch sử và Phân tích hỗ trợ version phù hợp. Tab IC hiển thị toàn bộ version có dữ liệu, số mẫu và thời gian cập nhật đã quy đổi sang giờ Việt Nam.

## Luồng dữ liệu

- `sync_data_daily.yml`: cập nhật OHLC 45 ngày, sync ledger gần đây, tính IC tổng và IC theo ngành.
- `sync_supabase.yml`: đồng bộ đầy đủ predictions/outcomes và các bảng IC khi cần backfill.
- `cron_weekly.yml`: hoàn thiện outcomes tuần, IC tổng và IC theo ngành.
- Workflow không có lịch schedule bắt buộc; n8n là bộ điều phối bên ngoài.
- Sau sync, workflow gọi `/api/revalidate`; cặp secret GitHub/Vercel đã cấu hình và được kiểm chứng bằng workflow thật. TTL 5 phút vẫn là cơ chế dự phòng.

## Mốc cải thiện 2026-10-14

- Dùng truy vấn metadata mới nhất theo từng version thay vì tải hàng nghìn run.
- Sửa tab Hôm nay dùng đúng version đang chọn; thêm panel trạng thái độ mới dữ liệu mà không thay header.
- Lịch sử lọc đúng version và outcome join theo version, tránh trộn bản ghi cùng mã/thời điểm.
- Phân tích tải tập gần nhất và hỗ trợ tìm chính xác toàn bộ lịch sử theo mã.
- Hiển thị riêng lỗi truy vấn và trạng thái không có dữ liệu.
- Tối ưu bảng IC trên mobile, bổ sung dark/light/system theme.
- Bổ sung revalidation có secret, CI lint/typecheck/build và cấu hình region Vercel.
- Migration `0028_optimize_app_settings_policy.sql` đã áp dụng để tối ưu RLS policy bằng `(select auth.jwt())`.
- Chuẩn hóa lint cho Next.js 15 và bổ sung `npm run check`.
- Thu gọn `v4_signals.breakdown` thành serving projection: giữ field UI/drill-down và toàn bộ biến numeric cho Phân tích/IC; ledger Git vẫn là nguồn lossless. Kiểm thử trên 80.630 signal thuộc 6 version review cho thấy JSON payload giảm 31%.
- Migration `0029_compact_signal_serving_payload.sql` tăng tần suất autovacuum/analyze cho `v4_signals`; cấu hình đã áp dụng production.
- Migration `0030_prune_unserved_dashboard_data.sql` đã áp dụng production: bỏ version không phục vụ, batch IC ngành cũ và OHLC quá 900 ngày; các exporter tiếp tục tự giữ đúng retention.
- Tab Phân tích coi timeline là dữ liệu bắt buộc; timeout của view tương quan phụ không còn làm trắng toàn bộ trang. Production vẫn có 949 signal-ngày BUY của v4.18 đến 2026-10-13.

## Bảo mật và dữ liệu

- Client chỉ dùng Supabase anon/publishable key; service-role key chỉ nằm trong workflow/server-side scripts.
- Endpoint revalidation dùng secret server-only và so sánh constant-time.
- Cleanup production được giới hạn rõ: OHLC giữ 900 ngày, IC ngành giữ batch `ready` mới nhất, và chỉ 6 scoring version review được lưu. Ledger Git không bị xóa. Chi tiết: `docs/DATA_RETENTION.md`.
- Không tự sửa/xóa bảng của ứng dụng khác trong Supabase project dùng chung.

## Cấu hình cần xác nhận ngoài repo

- DONE — Vercel `REVALIDATE_SECRET` và GitHub `DASHBOARD_REVALIDATE_SECRET` đã được đặt cùng giá trị, lưu dạng secret và không ghi vào repo.
- DONE — Vercel “Ignored Build Step” = `git diff HEAD^ HEAD --quiet -- .`; Functions region = `hnd1`.
- Nếu Supabase tiến gần giới hạn dung lượng, ưu tiên tạo project riêng cho dashboard; đây là thay đổi hạ tầng cần owner/billing và migration có kiểm soát.

## Kiểm chứng trước bàn giao

- PASS — YAML parse: 12 workflow.
- PASS — ESLint không có warning/error.
- PASS — TypeScript `tsc --noEmit`.
- PASS — Next.js production build, 9 static pages và các dynamic route được tạo thành công.
- PASS — security review route revalidation, truy vấn mới và Supabase policy; không có secret client-side hay advisory mới thuộc dashboard.
- PASS — production deployment `dpl_2DVC47gS7ApgLVddiVx2ygS8QKHD` READY tại region `hnd1`; endpoint revalidation trả `401` khi thiếu token.
- PASS — GitHub Actions run `38445496196`: OHLC, ledger, IC tổng, IC theo ngành và revalidation đều success.
- PASS — sau run: IC tổng `2026-10-13 18:25:51 UTC`, IC ngành `2026-10-13 18:25:57 UTC`, 136 dòng IC tổng và 14.456 dòng IC ngành.
- Hạn chế — production route sau đăng nhập cần session owner để visual QA đầy đủ.

## Việc tiếp theo

- Theo dõi dung lượng Supabase hằng tháng theo `docs/DATA_RETENTION.md`; snapshot trước retention 2026-10-14/15 khoảng 350 MB (~70% mốc 500 MB).
- Tách Supabase project khi cần độc lập quota hoặc isolation với các ứng dụng khác.

## Mốc dashboard insight & serving 2026-10-14

- Giữ nguyên header; thêm dải insight ưu tiên cho Buy, Hôm nay, IC và Phân tích.
- Hôm nay có thống kê chuyển trạng thái và heatmap mã × snapshot; Lịch sử có tên công ty và outcome 3/5 phiên.
- Buy hiển thị guardrail mẫu/độ bền; chart mặc định gọn và có chế độ nâng cao.
- Phân tích hỗ trợ cùng cửa sổ thời gian, calibration theo quintile và đọc chẩn đoán từ snapshot thay vì chạy ba view tương quan nặng trên request.
- IC hiển thị ma trận factor × version, coverage theo version và chỉ xếp hạng ngành khi n≥30.
- Migration `0031_dashboard_insight_snapshots.sql` đã áp dụng production. Lần refresh kiểm chứng: 5.936 diagnostics, 136 IC-history rows và 6 version summaries.
- Quyền đã kiểm: anon/authenticated chỉ SELECT snapshot; chỉ service role được EXECUTE hàm refresh.
- Kiểm tra local: ESLint, TypeScript, Python compile, 12 workflow YAML và Next.js production build đều PASS.

- PASS — commit ứng dụng `dafc5cc9` đã push lên `main`; GitHub commit status xác nhận Vercel deployment `3YMyt4GiRX6roVRCpiDLQSj43X7U` thành công.

## Tinh chỉnh không gian hiển thị 2026-10-14

- Tab Hôm nay gộp thống kê chuyển trạng thái BUY và heatmap mã × snapshot vào một bảng `details`, mặc định đóng sau mỗi lần tải trang.
- Tab Mua đặt bộ chọn scoring version dạng compact cùng hàng với tiêu đề; dòng mô tả chỉ còn thời gian cập nhật để bỏ nội dung trùng.
- Xác minh: ESLint, TypeScript và Next.js production build PASS; `/buy` và `/today` vẫn được auth gate redirect đúng khi chưa đăng nhập.
- Hạn chế visual QA: chưa kiểm tương tác sau đăng nhập trên browser vì không có session owner; đã review code cho desktop/mobile, wrapping và touch target.
## Tinh chỉnh insight Mua và horizon IC 2026-10-14

- Tab Mua gom toàn bộ thống kê BUY và insight chất lượng vào một khối mở/đóng dùng chung cho cả trạng thái có và không có tín hiệu; khối mặc định đóng khi tải trang.
- Tab IC bỏ horizon 1 phiên khỏi giao diện đánh giá và so sánh; các bảng IC, cỡ mẫu và ma trận factor × version tập trung vào 3, 5 và 10 phiên. Dữ liệu 1 phiên trong nguồn không bị xóa.
- Khối tóm tắt “Chất lượng IC theo thời gian nắm giữ” đã được gỡ theo yêu cầu; tab IC bắt đầu bằng bảng so sánh factor × scoring version, còn các bảng IC và cỡ mẫu 3/5/10 phiên bên dưới được giữ nguyên.
- Xác minh local: ESLint, TypeScript và Next.js production build PASS. Visual QA sau đăng nhập vẫn cần session owner; code đã được rà cho trạng thái rỗng, desktop/mobile và bảng cuộn ngang.

## Điều khiển lớp chart Mua 2026-10-14

- Chart tab Mua có checkbox Chọn tất cả hiển thị trực tiếp dưới chart: bật toàn bộ 9 lớp chỉ báo hoặc tắt toàn bộ; thay đổi từng lớp đưa preset về trạng thái tùy chỉnh.
- Xác minh local: ESLint, TypeScript và Next.js production build PASS. Visual QA tương tác sau đăng nhập chưa chạy vì không có session owner.
## Thu gọn bảng đối chiếu IC 2026-10-14

- Hai khối “So sánh factor × scoring version” và “Phạm vi dữ liệu dùng khi đối chiếu version” dùng `details`, mặc định đóng sau mỗi lần tải trang và chỉ hiện nội dung khi người dùng mở.
## Retention theo version 2026-10-15

- v4.18 và v4.17 giữ full intraday trên Supabase; v4.9, v4.8, v4.1, v2.3 chỉ giữ run cuối ngày và run BUY cuối ngày.
- Tab IC lấy factor × version từ v4_ic_metrics, indicator từ v4_marginal_ic, IC ngành từ batch v4_ic_industry_metrics; tab Mua cũng đọc IC ngành từ batch precompute.
- Migration 0032_retain_legacy_daily_signals.sql tạo RPC service-role-only; cả daily sync, manual full sync và weekly flow đều prune trước khi refresh snapshot/revalidate.
- Git ledger tiếp tục là nguồn lossless. Supabase là serving layer có retention; không chạy VACUUM FULL tự động.- Production prune 2026-10-15 đã xác minh: legacy signal 66.330 → 11.380, outcome 52.618 → 8.730, run 655 → 97. Kích thước vật lý vẫn khoảng 350 MB sau DELETE và sẽ tái sử dụng khoảng trống.
## Supabase cleanup 2026-10-15

- Production hiện có 28.080 signal, 19.230 outcome và 264 run; đã xóa 139 orphan run, không còn orphan/dead tuple.
- Migration 0033_prune_orphan_runs.sql và retention script ngăn orphan run tái tích lũy.
- Database vẫn khoảng 350 MB vật lý; live signal payload khoảng 43,5 MB. VACUUM FULL chưa chạy vì cần maintenance lock riêng.

## Backtest hybrid factor v4.17/v4.18 2026-10-15

- Đã kiểm tra source: v4.18 chỉ đổi trọng số TRADE so với v4.17; công thức/cap của 5 factor không đổi. Vì vậy lựa chọn MeanRev/Flow từ v4.17 và các factor còn lại từ v4.18 thực chất là bài toán chọn trọng số, không phải ghép giá trị factor khác nhau.
- Backtest ledger daily-last trên 2.100 mã-ngày, 21 ngày tín hiệu 2026-08-28 đến 2026-09-30; join outcome thật 3/5/10 phiên theo `pred_id`.
- Candidate đăng ký trước `hybrid_equal` (20% mỗi factor) tại 5d đạt daily IC +0,190 và top-20% excess +1,07%; 7 ngày mới nhất đạt IC +0,157 và excess +0,58%. Rank correlation score tái dựng so với ledger production là 0,974 cho v4.17 và 0,983 cho v4.18.
- Sensitivity `hybrid_no_mr` tốt hơn nhưng được hình thành sau khi xem dữ liệu nên có selection bias; chưa dùng làm production recommendation.
- Production scoring chưa đổi. Khuyến nghị chạy `hybrid_equal` dạng shadow tới khi có ít nhất 30 ngày outcome chín độc lập. Script: `backtest/backtest_hybrid_v417_v418.py`; báo cáo: `docs/HYBRID_BACKTEST_V417_V418.md`.
