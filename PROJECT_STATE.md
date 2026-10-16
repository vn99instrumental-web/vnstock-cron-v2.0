# PROJECT_STATE.md

**Cập nhật:** 2026-10-16
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

Theo thứ tự mới nhất: `v4.19-shadow`, `v4.18`, `v4.17`, `v4.8`, `v4.1`, `v2.3`. Production mặc định vẫn là `v4.18`.

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
- Cleanup production được giới hạn rõ: OHLC giữ 900 ngày, IC ngành giữ batch `ready` mới nhất, và chỉ 7 scoring version review được lưu. Ledger Git không bị xóa. Chi tiết: `docs/DATA_RETENTION.md`.
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

- v4.18 và v4.17 giữ full intraday trên Supabase; v4.19-shadow, v4.8, v4.1, v2.3 chỉ giữ run cuối ngày và run BUY cuối ngày. v4.9 đã ngừng từ 2026-10-16.
- Tab IC lấy factor × version từ v4_ic_metrics, indicator từ v4_marginal_ic, IC ngành từ batch v4_ic_industry_metrics; tab Mua cũng đọc IC ngành từ batch precompute.
- Migration 0032_retain_legacy_daily_signals.sql tạo RPC service-role-only; daily sync, manual full sync và weekly flow refresh snapshot/revalidate trước rồi mới prune ở maintenance cuối.
- Git ledger tiếp tục là nguồn lossless. Supabase là serving layer có retention; không chạy VACUUM FULL tự động.
- Production prune 2026-10-15 đã xác minh: legacy signal 66.330 → 11.380, outcome 52.618 → 8.730, run 655 → 97. Kích thước vật lý vẫn khoảng 350 MB sau DELETE và sẽ tái sử dụng khoảng trống.
## Supabase cleanup 2026-10-15

- Production hiện có 28.080 signal, 19.230 outcome và 264 run; đã xóa 139 orphan run, không còn orphan/dead tuple.
- Migration 0033_prune_orphan_runs.sql và retention script ngăn orphan run tái tích lũy.
- Database vẫn khoảng 350 MB vật lý; live signal payload khoảng 43,5 MB. VACUUM FULL chưa chạy vì cần maintenance lock riêng.

## Backtest hybrid factor v4.17/v4.18 2026-10-15

- Đã kiểm tra source: v4.18 chỉ đổi trọng số TRADE so với v4.17; công thức/cap của 5 factor không đổi. Vì vậy lựa chọn MeanRev/Flow từ v4.17 và các factor còn lại từ v4.18 thực chất là bài toán chọn trọng số, không phải ghép giá trị factor khác nhau.
- Backtest ledger daily-last trên 2.100 mã-ngày, 21 ngày tín hiệu 2026-08-28 đến 2026-09-30; join outcome thật 3/5/10 phiên theo `pred_id`.
- Candidate đăng ký trước `hybrid_equal` (20% mỗi factor) tại 5d đạt daily IC +0,190 và top-20% excess +1,07%; 7 ngày mới nhất đạt IC +0,157 và excess +0,58%. Rank correlation score tái dựng so với ledger production là 0,974 cho v4.17 và 0,983 cho v4.18.
- Sensitivity `hybrid_no_mr` tốt hơn nhưng được hình thành sau khi xem dữ liệu nên có selection bias; chưa dùng làm production recommendation.
- Production scoring chưa đổi. `hybrid_equal` là benchmark lịch sử và đã được thay trong shadow bởi cấu hình IC-weighted ghi ở phần kế tiếp. Script: `backtest/backtest_hybrid_v417_v418.py`; báo cáo: `docs/HYBRID_BACKTEST_V417_V418.md`.

## Forward shadow v4.19 2026-10-15

- `v4.19-shadow` materialize từ cùng snapshot v4.18; trọng số IC cố định MeanRev/Breakout/Flow/Fund/Growth = 5/15/20/25/35, context 0 và không cộng confluence/flow extras. Không gọi thêm market API.
- Batch equal-weight đầu tiên (1 run/100 signal, chưa có outcome) đã được xóa khỏi Supabase và ledger trên `main` trước khi ghi dữ liệu IC-weighted, nên không còn lịch sử trộn phương pháp. Mỗi prediction mới có trace `ic_shrunk_fixed_core` và profile `mr5_bo15_flow20_fund25_growth35` để audit.
- Production mặc định, decision v4.18 và feed thông báo/Zalo không đổi. Shadow có ledger/outcome/version selector riêng; Supabase chỉ giữ daily-close và daily-BUY.
- Trên mẫu thiết kế 21 ngày/2.100 mã-ngày, trọng số làm tròn đạt IC 5d +0,222 và top-20% excess +1,44%, nhưng vẫn là kết quả trong mẫu. Chỉ review promote sau tối thiểu 30 ngày outcome chín độc lập.
- Supabase migration `0034_add_v419_shadow.sql` đã áp dụng: view phân tích nhận shadow; retention giữ daily-close và daily-BUY. View dùng `security_invoker`; RPC prune chỉ `service_role` được execute.
- Tài liệu công thức, cơ sở và checklist monitor: `docs/V419_SHADOW_WEIGHTING.md`.
- Xác minh: 5 unit test PASS; materialize 100/100 mã; payload sync giữ đủ trace; ESLint, TypeScript và Next.js production build PASS. Deployment production cho commit công thức `eeebb4c6` READY; Supabase và ledger hiện có 0 row equal-weight.

## So sánh Hôm nay và backfill v4.19 2026-10-15

- Tab Hôm nay cố định ba cột `v4.17`, `v4.18`, `v4.19`; mỗi ô mở được timeline snapshot và factor của đúng version. Khi bật đồng thời “Có ở cả 3” và “Có BUY/STRONG BUY”, mã chỉ được giữ lại nếu quyết định mới nhất của cả ba version đều là `BUY` hoặc `STRONG BUY`.
- Query tách theo version để không bị giới hạn 1.000 row của Supabase làm mất ngẫu nhiên một version khi tải trang; mobile dùng bảng cuộn ngang.
- Ledger bổ sung 2.000 row `v4.19-shadow` hồi cứu: 100 mã × 20 ngày trước 2026-10-15, lấy snapshot cuối ngày từ nguồn v4.18.
- Row hồi cứu không có entry/SL/TP, được gắn `shadow_data_origin=retrospective_backfill` và `shadow_forward_eligible=false`; evaluator và exporter IC loại các row này. Dữ liệu forward mới được gắn `forward/true`.
- Batch equal-weight cũ 100 row bị loại khi backfill; chỉ giữ cấu hình `ic_shrunk_fixed_core` cho chuỗi v4.19.
- Xác minh local: 6 unit test PASS, Python compile PASS, ESLint/TypeScript không có error và Next.js production build PASS. Visual QA sau đăng nhập còn phụ thuộc session owner.
- PASS — commit `97dcd9ce` đã push lên `main`; production deployment `dpl_HwwBcfieYCdnLnkot8e8Sj9Y33Tk` READY và alias `trading-snapshot-dl.vercel.app` trỏ đúng commit này.
- PASS — Supabase có 2.000 row backfill từ 2026-09-17 đến 2026-10-14, không row nào có entry/SL/TP; có 100 row forward IC-weighted ngày 2026-10-15 và 0 row equal-weight sau cleanup.

## Ổn định workflow và tab Hôm nay 2026-10-16

- Digest tab Hôm nay được tái hiện là `TODAY_COMPARE_VERSIONS.flatMap is not a function`: Server Component đã import runtime value từ module `use client`. Hằng số ba version đã chuyển sang `web/lib/today-compare.ts`; module production render lại thành công với dữ liệu Supabase thật.
- Retention RPC có timeout function 60 giây và anti-join outcome qua temp table có index. Production chạy 13,1 giây, xóa 17.800 legacy intraday signal, 8.700 orphan outcome và 178 run không còn liên kết; v4.17/v4.18 full intraday không thuộc phạm vi xóa.
- Workflow weekly/daily/manual refresh snapshot và revalidate cache trước khi chạy retention cuối luồng; lịch và concurrency n8n không thay đổi theo quyết định của owner.
- Snapshot refresh hằng ngày bỏ phép tính factor-pair vượt 60 giây khỏi critical path nhưng giữ snapshot pair gần nhất. Factor/split, IC history và version summary refresh production thành công trong 5,9 giây.
- Bảo mật RPC đã kiểm tra: anon/authenticated không có EXECUTE; service_role có EXECUTE. Security advisor không phát hiện advisory mới thuộc dashboard; các cảnh báo còn lại thuộc bảng/hàm khác trong Supabase project dùng chung.
- Kiểm tra local: Python compile PASS, 12 workflow YAML parse PASS, ESLint/TypeScript không có error và Next.js production build PASS. Server module `/today` chạy thành công với dữ liệu thật sau sửa.
- PASS — commit chức năng `42848b2f` đã push lên `main`; Vercel deployment `dpl_3myo7hsopeL59LmQwhqZWCKuymQ2` READY và production alias trỏ đúng commit này.

## Sửa weekly snapshot refresh 2026-10-16

- Run weekly `105227137731` hoàn tất eval, commit ledger, sync outcome, IC tổng và IC ngành nhưng lỗi tại dashboard snapshot với PostgreSQL `21000: DELETE requires a WHERE clause`.
- Nguyên nhân là RPC `refresh_v4_dashboard_snapshots()` xóa toàn bộ bảng version summary mà không có điều kiện, bị lớp safe-update của production chặn.
- Migration `20261016002114_fix_dashboard_snapshot_safe_delete.sql` dùng predicate trên khóa chính `scoring_version is not null`; vẫn thay toàn bộ snapshot trong transaction và tránh exclusive lock của `TRUNCATE`.
- Workflow tiếp tục chỉ dùng `workflow_dispatch`; n8n vẫn là bộ điều phối bên ngoài, không thêm GitHub schedule.
- Production RPC đã chạy lại thành công: 243 factor, 464 split, 5.150 pair được giữ, 408 IC-history và 7 version summary; snapshot refresh lúc `2026-10-16 00:21:25 UTC`. Quyền execute vẫn chỉ cấp cho `service_role`.
