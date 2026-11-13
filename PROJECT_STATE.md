# PROJECT_STATE.md

**Cập nhật:** 2026-11-04
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

Theo thứ tự mới nhất: `v4.19-shadow`, `v4.18`, `v4.17`, `v4.8`, `v4.1`, `v2.3`. Dashboard mặc định hiển thị `v4.19-shadow` khi có dữ liệu; scoring production vẫn là `v4.18`.

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

## Điều chỉnh ledger 2026-10-29

- `output/history/v2f_predictions_v4` chuyển từ partition tháng `YYYY-MM.jsonl` sang partition ngày `YYYY-MM-DD.jsonl` để không tạo blob vượt giới hạn 100 MB của GitHub.
- Reader Supabase, weekly evaluator và QC đọc tương thích cả file tháng cũ lẫn file ngày mới; dữ liệu lịch sử không bị mất và không cần Git LFS.
- Workflow intraday chặn sớm staged file lớn hơn 95 MB với thông báo rõ trước bước commit/push.
- File tháng 10 cũ được giữ nguyên làm lịch sử; recorder không ghi thêm vào file này.

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

## Ngừng scoring v4.9 2026-10-16

- v4.9 đã bị loại khỏi review config, historical scorer manifest, workflow label và selector dashboard; từ run kế tiếp GitHub không còn tính hoặc ghi record v4.9. Công thức production v4.18 không thay đổi.
- Migration `20261016011829_retire_v49_data.sql` đã xóa production: 920 signal, 400 outcome, 8 run và 1.402 dòng IC/snapshot; kiểm tra sau xóa cho thấy 0 dòng v4.9 trong cả 10 bảng liên quan.
- Dung lượng nội dung hàng trước xóa là 1.639.102 byte (~1,60 MB), ước khoảng ~2 MB nếu phân bổ thêm index. `DELETE` tạo vùng trống tái sử dụng; database vật lý vẫn khoảng 352 MB và không chạy `VACUUM FULL`.
- Với nhịp quan sát 115 signal/ngày giao dịch, ngừng v4.9 tránh tăng khoảng 4–6 MB/tháng tùy outcome/index.
- Dashboard summary production còn 6 version: v4.19-shadow, v4.18, v4.17, v4.8, v4.1 và v2.3; snapshot refresh thành công lúc `2026-10-16 01:18:29 UTC`.
- Retention RPC không còn nhắc v4.9; anon/authenticated không có quyền execute và chỉ `service_role` được gọi.
- Git ledger lịch sử không bị rewrite, nên vẫn có thể phục hồi có chủ đích nếu owner thay đổi quyết định.

## Dashboard default version 2026-10-16

- Tabs with a version selector default to `v4.19-shadow` when it has data, preserve an explicit valid URL selection, and otherwise fall back to the newest review version that has data.
- The Today comparison remains three-version but orders columns `v4.19`, `v4.18`, `v4.17`; IC still shows all available versions and treats v4.19 as current only when official IC exists.

## Historical IC for v4.19 backfill 2026-10-16

- v4.19 forward IC remains isolated in `v4_ic_metrics`; retrospective rows are never written there.
- `scripts/export_backfill_ic_to_supabase.py` joins each audited v4.19 backfill prediction to its v4.18 source outcome and writes `v4_ic_backfill_metrics`.
- The IC tab uses forward rows when available; otherwise it shows the historical v4.19 rows with an explicit `backfill lịch sử` label in both the version table and factor × version matrix.
- Daily, weekly, and manual Supabase workflows refresh this separate historical layer before dashboard snapshot/cache refresh. Workflows remain `workflow_dispatch`-driven by n8n; no GitHub schedule was added.
- Production verification: 24 rows across six non-constant factors, 1,200 matured observations for each horizon, signal range 2026-09-17 through 2026-10-02. Context is absent because its backfill score has no cross-sectional variance.

## Hybrid Supabase/GitHub serving (2026-11-02)

- Supabase Auth and the current run/scoring workflows remain unchanged.
- Owner sees two explicit buttons, Supabase and GitHub. Dashboard datasets fall back to Supabase when a GitHub release is missing.
- Manual-only snapshot workflow publishes atomic current/previous JSON releases with SHA-256 manifest validation.
- Local verification passed: TypeScript, ESLint, Next.js production build, security review and authenticated-boundary smoke tests.

## GitHub serving doc lap (2026-11-03, thay the muc hybrid 2026-11-02)

- Supabase Auth duoc giu nguyen. Hai nut Supabase/GitHub doc dung nguon da chon; khong fallback am tham. GitHub la mac dinh khi khong co env/cookie ghi de.
- Workflow intraday do n8n dispatch dung `output/serving/current` truc tiep tu ledger cua chinh run, validate manifest/hash/kich thuoc, commit cung ledger, push roi revalidate Vercel. Supabase sync chay sau nhu mirror non-blocking.
- Daily workflow ghi OHLC vao `output/ohlc`, dung full GitHub release va publish truoc cac buoc Supabase. Loi Supabase mirror khong lam hong local OHLC export.
- Weekly workflow dung full release sau khi hoan tat outcome; forward IC duoc tinh lai tu prediction/outcome ledger local. Workflow manual serving cung dung local ledger, khong can Supabase key.
- Publisher deduplicate theo version/pred_id, gan `source_provenance=git-ledger`, giu moi serving blob duoi 20 MiB va xoa ban `previous` trung lap; Git history la rollback.
- Full publisher tu tinh forward IC, IC theo nganh, BUY expectancy va BUY robustness tu ledger Git; khong can doc Supabase. Intraday giu cac metric tu full release gan nhat.
- Dry-run thuc te: 100 signal moi nhat cho ca 6 version, release khoang 71.3 MiB, file lon nhat khoang 6.2 MiB.
- Detail cua run moi doc truc tiep JSONL partition trong Git thay vi Supabase, tranh nhan doi ledger trong serving release.

### Verification 2026-11-03

- PASS: publisher intraday dry-run va `--full --dry-run`; full IC tao 144 dong cho du 6 version review.
- PASS: Python compile cho publisher/OHLC exporter; YAML parse cho 4 workflow thay doi.
- PASS: TypeScript, ESLint va Next.js production build (15 route).
- PASS: security review khong thay service-role key/client secret bi dua sang frontend; API chart van yeu cau Supabase Auth; revalidation van dung server secret constant-time.
- Chua chay authenticated browser flow vi worktree khong co owner session. Can smoke test hai nut tren Vercel sau merge/deploy.
- Gioi han da biet: detail GitHub truoc luc ledger v4 chuyen sang partition ngay co the khong mo duoc; list/history/chart van co data. Khong sao chep file thang 10 gan 100 MiB vao serving layer.


## GitHub-independent hardening (2026-11-03)

- n8n workflow `gy5bMCRrABkdbjEc` keeps its existing schedule, GitHub dispatch and fixed 15-minute wait. Active version `46a909e3-1edc-49c9-b148-b22d5390f891` routes only to the two v4.17 Zalo inputs; legacy v2.3/v4 publication branches remain on canvas but are disconnected. Both v4.17 GitHub writes retry up to three times on transient conflicts.
- All seven GitHub Actions workflows that write to `main` share concurrency group `vnstock-main-writer` with queueing instead of cancellation. The manual serving publisher retries pull/rebase/push up to five times.
- Serving manifests are built only by scanning the finished staging tree. Dataset paths are relative and unique; SHA-256 and the 20 MiB per-file guard remain mandatory.
- A full GitHub build recomputes official daily IC, pooled indicator/factor IC, marginal IC, industry IC and analysis factor/pair/split diagnostics from the Git ledger plus local OHLC. Intraday builds preserve analytics `generated_at` and only advance `published_at`.
- Supabase Auth and the Supabase mirror remain unchanged for source comparison. Vercel keeps the ignored-build command `git diff HEAD^ HEAD --quiet -- .`, so data/docs-only commits do not replace the production web deployment.
- Verification: final full rebuild on the latest weekly ledger completed in about 1m03s; 726 unique relative datasets, largest 6,400,454 bytes; 144 official IC, 68 indicator IC, 160 factor-version IC, 320 marginal IC and 1,152 industry IC rows; latest signal count is 100 for each of six review versions.

## OHLC parity Supabase/GitHub (2026-11-04)

- Root cause of the Buy-chart mismatch: the daily workflow fetched 45 calendar days and replaced each `output/ohlc/<symbol>.json`, while Supabase retained 900 days. SHB had 32 GitHub bars versus 616 Supabase bars.
- `export_ohlc_to_supabase.py` now supports a one-time/recovery Supabase-to-GitHub OHLC seed and merges subsequent rows by `(symbol, date)` instead of truncating history. Both stores use the same 900-day cutoff.
- `sync_data_daily.yml` exposes `bootstrap_ohlc_from_supabase`; normal n8n dispatches keep the input false and remain GitHub-independent after the seed. The service-role key remains server-side in GitHub Secrets.
- Verification complete: Python compile, three OHLC unit tests, workflow YAML parse and `git diff --check` pass. Production run `41748550325` succeeded and published data commit `c736adeb`; SHB matches exactly at 615 bars from 2024-05-20 through 2026-11-03 in Supabase, `output/ohlc` and the GitHub serving chart. The 726-dataset manifest has no missing, duplicate or SHA-256-mismatched files.
## Dashboard source parity (2026-11-04)

- Analysis parity: Supabase had 1,990 v4.19 rows in the database, but the UI received only 1,000 because one PostgREST response was capped. The Supabase path now reads two deterministic 1,000-row pages; GitHub and Supabase both expose 1,007 v4.17, 1,534 v4.18 and 1,990 v4.19 analysis rows.
- Today parity: the GitHub publisher now retains every intraday snapshot from the newest signal date instead of only the latest run. Production snapshots contain 500 rows, five snapshot times and 100 symbols for each of v4.17, v4.18 and v4.19.
- Price change parity: GitHub computes `previous_close` and `changePct` from the same prior-session OHLC rule as Supabase. The Today page now binds the percentage to the exact latest price snapshot instead of the first same-symbol row.
- Factor verification: production GitHub/Supabase `pred_id` hashes match for all three Today versions. Coverage counts also match for all six factor groups, `s_ff_net`, `ff_intra_net`, and entry/stop/tp1.
- Verification PASS: Python compile, publisher dry-run/manifest checks, TypeScript, ESLint, Next.js production build, security review, GitHub Actions run `41753270325`, data commit `886ee833`, and Vercel deployment for code commit `cdf0e57a`.
- Auth boundary smoke test PASS: unauthenticated `/today` and `/phan-tich` redirect to login with no browser console errors. Authenticated source-button interaction still requires the owner's existing login session for visual testing.

## GitHub/Supabase history parity and automatic audit (2026-11-04)

- Root cause of missing GitHub historical outcomes: the full publisher loaded all outcome partitions for analytics, but History merged only the two recent months. Full builds now enrich every retained History signal from the complete outcome ledger without restoring signal rows removed by serving retention.
- Production GitHub and Supabase are aligned for all six review versions on retained signal `pred_id` sets, embedded outcome `pred_id` sets, and latest run metadata. Verified counts include v4.17 = 14,100 signals / 9,400 outcomes and v4.18 = 16,200 signals / 11,500 outcomes.
- Latest production run at verification is `2026-11-04_13:13_*`; each version has universe size 100 and matching BUY counts in both sources.
- `scripts/verify_supabase_mirror.py` is read-only. Intraday checks the latest run after mirror sync; daily, weekly and manual sync also compare retained History signals and outcomes after retention. Audit failure is visible but non-blocking so GitHub remains authoritative and independent from Supabase availability.
- Verification PASS: Python compile, parity smoke test, YAML parse for 13 workflows, `git diff --check`, full ledger dry-run, security review, production full-build run `41789223365`, and read-only production SQL/Git hash comparison. Largest History file after outcome enrichment is 7.36 MiB, below the 20 MiB serving guard.
- The production full build published data commit `f7aa0df3`. The new parity step itself will first execute on the next intraday/daily/weekly/manual mirror workflow; no manual retention workflow was triggered during this verification.

## VNStock workflow cache stability (2026-11-05)

- Intraday runs alternated between success and cache miss while GitHub rolled out two Ubuntu 26.04 runner images. `actions/setup-python` resolved `3.11` to 3.11.17 on the old image and 3.11.18 on the new image.
- The old cache key included that setup-Python patch even though the cached VNStock environment owns a different Python under `/opt/vnstock/.venv`. Runs on 3.11.18 therefore could not see the cache created with the 3.11.17 key.
- Daily, intraday, V4 backfill, weekly, and daily Supabase sync now key the VNStock cache by Ubuntu version, runner architecture, and ISO week. They can migrate the prior same-Ubuntu v5 Python-patch cache.
- Weekly run `41991776979` restored the legacy OS-agnostic v4 cache but its venv failed with exit 127 on Ubuntu 26. Weekly now consumes the same compatible v5 cache as daily and intraday.
- Daily Supabase sync runs `41992391250` and `41993902442` failed in the OHLC step after accepting an untested legacy v4 venv. The workflow now executes an import probe before selecting the cached runtime and falls back to setup Python when the probe fails.
- Daily rebuilds only when its explicit environment validation fails, so a valid migrated cache is not discarded merely because the primary key was a partial match.
- Verification: all 13 workflow YAML files parse, the five production cache blocks use the stable key and migration prefix, `git diff --check` passes, and the workflow/security review found no new secret or permission exposure.

## VNStock generation 6 dashboard source (2026-11-09)

- `vnstock6` is a third owner-selectable dashboard source beside Supabase and GitHub. Today, Buy, History, Analysis, Charts, history detail, and IC all route through the generation 6 adapter.
- The current serving mode is explicitly `bridge`, not native scoring: current GitHub scoring data is filtered to the 1,517-symbol SSI generation 6 universe. IC and diagnostics remain upstream aggregate values. Every Gen6 page shows this provenance and links to `/vnstock6`; an invalid or missing manifest fails visibly without a silent fallback.
- `output/vnstock6-preview/dashboard.json` is the published contract. It records package/source provenance, the complete sorted SSI symbol universe, eight dashboard capabilities, and stage status. Authentication and SSI reference discovery are native and successful; native market ingestion and scoring are pending; serving is successful in bridge mode.
- The independent target is `output/serving/vnstock6/current`, with separate environment/cache, explicit SSI calls, no imports from the old VNStock runtime, no secrets in artifacts, and no promotion until native ingest, scoring, serving, and parity checks pass. See `docs/vnstock6-flow.md`.
- Production contract verification: all current dashboard symbols belong to the SSI universe. Gen6 exposes 400 Today rows per reviewed version; Buy counts 31/37/48; History counts 15,600/17,700/9,700; Analysis counts 1,558/2,000/2,000; and 100 chart symbols for v4.17/v4.18/v4.19-shadow respectively. The bridge IC payload contains 144 metrics, 68 indicators, 160 factor-version rows, 320 marginal rows, and 1,152 industry rows.
- Verification PASS: Python contract builder and validator, negative secret-field validation, TypeScript, ESLint, Next.js production build, `git diff --check`, auth boundary checks, and security review. GitHub Actions runs `42575164346` (web quality) and `42575241241` (Gen6 comparison/publish/revalidation) succeeded. Data commit `2400b625` was published, and Vercel deployment `dpl_4xzBaKRaBejTtkULH25ZcYLbx3YS` is READY.
- Authenticated rendered visual interaction was not completed because the Chrome control bridge failed during navigation. Responsive and empty/error states were reviewed in code; unauthenticated login redirect and source-switch authorization were verified.

## VNStock generation 6 native data plane (2026-11-12)

- Gen6 was upgraded from RC4/OAPI RC3 to final `vnstock==6.0.0` and `vnstock-oapi==0.1.1`; the fixed GitHub Actions device identity is reused to avoid ephemeral-runner registrations.
- Source diagnostic run `43145031631` passed: SSI reference returned 1,518 symbols; SSI and FHSC OHLC both succeeded; FHSC balance sheet, income statement and cash flow routes succeeded. GitHub secret `FINHAY_API_KEY` is mapped only at runtime to the connector variable `FHSC_API_KEY`.
- Native candidate run `43147270125` passed end to end with 100/100 symbols, 100 serving rows and no failed symbols. Market primary was SSI; FHSC fallback was not needed. Web quality run `43146464653` passed.
- Native production data run `43147920968` published commit `ad4a9fa1`: generation-6 ledger/status and 106 isolated serving datasets under `output/serving/vnstock6/current`. The public dashboard manifest deliberately remains `mode=bridge`; no Vercel deployment or dashboard activation occurred.
- `vnstock6_native_production.yml` is the n8n/manual entry point for intraday/daily/weekly modes and shares the `vnstock-main-writer` lock. `activate_dashboard` defaults to false and must stay false until the compatible web release is deployed.
- Current `v6.0-native` is technical-only. FHSC fundamental routes are health/schema checked and provenance is recorded, but fundamental values are not yet included in scoring. It is not numerically equivalent to v4.18/v4.19.
- A transient FHSC cash-flow network error in the first production publish was handled with bounded retries. Verification run `43148729804` published commit `2738d7f5` with all three FHSC statements successful on attempt 1 and `fundamental_status=available_not_scored`; dashboard mode remained `bridge`.

## Gen 6 intraday restart 2026-11-12

- `vnstock6_native_production.yml` is the only Gen 6 writer entry point for n8n. The documented cadence is five weekday triggers in `Asia/Ho_Chi_Minh`: 09:15, 10:30, 11:30, 13:45 and 14:50.
- Every successful run fetches SSI with FHSC fallback, publishes the isolated Gen 6 Git/serving release and revalidates Vercel. Intraday runs keep derived work incremental; daily/weekly modes rebuild full IC/analysis.
- Active scorer is `v6.1-availability`, adapted from the production factor contract. Missing factor inputs are recorded per symbol and excluded with weight renormalization; they are never silently treated as zero. Fundamental and growth remain excluded until per-symbol FHSC normalization exists.
- n8n workflow `AAUC60oWWlwKunaR` (`VNStock Gen6 intraday`) is published and active with the five documented weekday schedules and `Asia/Ho_Chi_Minh`. It dispatches production through the stored `GitHub account` credential; no token is embedded in its two nodes.
- Availability-aware candidate run `43178700815` passed. Production run `43179238229` passed and published data commit `845cbce2` with 100/100 symbols and zero failed symbols.
- The serving release contains 100 `v6.1-availability` rows. All rows declare `exclude_and_renormalize`; fundamental and growth were unavailable for scoring and explicitly excluded from all 100 rows.
- Vercel commit status is successful and `/vnstock6` responds, but anonymous requests redirect to `/login`; authenticated rendered-data verification remains a separate owner-session smoke test.

## Gen 6 data cadence split 2026-11-13

- Gen 6 now has three serialized writer cadences under the shared vnstock-main-writer concurrency group.
- The existing n8n workflow remains responsible for five weekday intraday dispatches. Intraday reads only market OHLCV, calculates technical/scoring output, publishes serving data and revalidates Vercel.
- Existing OHLC history is merged from a 14-day correction window; the 500-day request is used only when a symbol has no local history.
- Intraday no longer calls FHSC balance sheet, income statement or cash flow endpoints and no longer evaluates every historical outcome five times per day.
- vnstock6_daily_maintenance.yml runs at 16:15 ICT on weekdays. Before outcomes/IC/analysis, it checks the legacy adaptive BCTC TTL (3 days in earnings months, otherwise 30 days), refreshes only stale/missing FHSC symbols, preserves last-known-good entries on failure, then commits and revalidates Vercel.
- vnstock6_fundamental_refresh.yml runs at 09:15 ICT on Sundays. It refreshes SSI reference membership and FHSC statements, calculates vnstock_quant.fa ratios/growth, validates secret-free artifacts and commits the cache.
- A failed symbol refresh preserves the last successful cache entry. Entries older than the active 3/30-day TTL are excluded from Fundamental/Growth with weight renormalization and the reason fundamental_cache_stale.
- The candidate workflow probes the separated fundamental path with three symbols before market/scoring. It may report `PASS_DEGRADED` only after verifying unavailable fundamental/growth factors are excluded and weights renormalized; the weekly workflow remains the hard freshness gate.
- Local verification: Python compile PASS; six focused unit tests PASS after retries around the known intermittent Windows native process crash; git diff --check PASS. Security review found no committed secret, client exposure or new authorization boundary.
- Production bootstrap run 43338517181 succeeded and published commit fe613b7a: FHSC/vnstock_quant cache 100/100, v6.2-quant serving 100/100 and 300 matured outcomes. The first post-split intraday run 43350792238 also succeeded without a BCTC refresh.
- Candidate run 43350815066 passed on Linux: SSI OHLCV 100/100, FHSC refresh sample 3/3, 174 fundamental/growth scored rows and 26 availability exclusions. First scheduled daily/weekly runs and authenticated dashboard review remain operational checks in docs/VNSTOCK6_TASKS.md.

## Gen 6 adaptive slow-data refresh fix 2026-11-13

- Five n8n intraday triggers remain OHLCV-only so a slow FHSC refresh cannot block or collapse the market-session cadence.
- Daily maintenance at 16:15 ICT now runs fundamentals --stale-only: fresh cache makes zero source calls; only stale/missing symbols fetch BCTC and recalculate vnstock_quant.fa.
- The TTL matches cron v2.0: 3 days in earnings months 1/2/4/5/7/8/10/11, 30 days otherwise. Sunday weekly remains a full refresh safety net.
- Candidate validation no longer treats an absent refresh-status file as a data failure when serving rows contain valid calculated factors. Missing/stale factors still must be excluded and weights renormalized.
- Local verification: Python compile, JSON parse, nine focused tests and git diff check passed. Security review found secrets remain GitHub server-side only and status/cache artifacts contain no credential values.