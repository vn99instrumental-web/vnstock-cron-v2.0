# PROJECT_STATE.md

**Cập nhật:** 2026-11-04
**Branch production:** `main`
**Dashboard:** <https://trading-snapshot-dl.vercel.app>

## Quy ước phân tích cổ phiếu bằng Gen6 — 2026-11-17

Đối với **báo cáo phân tích từng mã**, ưu tiên Gen6 trong `output/serving/vnstock6/current/` làm **nguồn kỹ thuật**. Kiểm tra `output/vnstock6/native-status.json` và `output/serving/vnstock6/current/metadata.json` mỗi lần truy xuất. Profile chính tại ngày cập nhật: `v6.4.18`; `v6.4.19-shadow` chỉ đối chiếu. Không lấy score/decision V4 cũ để nhận định kỹ thuật hiện tại. Chi tiết: [docs/STOCK_ANALYSIS_GEN6_SOURCE.md](docs/STOCK_ANALYSIS_GEN6_SOURCE.md).

**Phạm vi thay đổi:** quy ước nguồn cho trợ lý/agent nghiên cứu; không thay đổi công thức scoring, lịch chạy, dashboard hay ledger. Các mô tả V4 phía dưới giữ làm lịch sử của phiên bản cũ.

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
- Query tách theo version để không bị giới hạn 1.000 row của Supabase làm mất�~}����k�w��p�Q���M�ɥ�а�M1��а�9��й�́�ɽ�Սѥ����ե����͕��ɥ��ɕ٥�ܰ���!Ո��ѥ��́�ո������������Հ����ф������Ё���ٕ���̀������Y�ɍ��������嵕�Ё��ȁ����������Ё�������݅��4(���Ѡ���չ����͵����ѕ�ЁAML�չ��ѡ��ѥ��ѕ����ѽ��倁�����������ѥ����ɕ��ɕ�ЁѼ�������ݥѠ�����ɽ�͕ȁ���ͽ�����ɽ�̸��ѡ��ѥ��ѕ��ͽ�ɍ�����ѽ����ѕɅ�ѥ����ѥ���ɕ�եɕ́ѡ���ݹ�ȝ́���ѥ���������͕�ͥ�����ȁ٥�Յ��ѕ�ѥ���4(4(�����!Ո�M�����͔����ѽ����ɥ�䁅�����ѽ��ѥ���Ց�Ѐ����ش�Ĵ�Ф4(4(��I��Ё���͔�������ͥ�����!Ո����ѽɥ������э�����ѡ���ձ���Չ��͡�ȁ�������������э�������ѥѥ��́��ȁ�����ѥ�̰���Ё!��ѽ�䁵�ɝ�������ѡ���ݼ�ɕ���Ё���ѡ̸�ձ���ե��́��܁��ɥ����ٕ��ɕх�����!��ѽ��ͥ������ɽ��ѡ��������є���э���������ȁݥѡ��Ёɕ�ѽɥ���ͥ�����ɽ�́ɕ��ٕ����͕�٥���ɕѕ�ѥ���4(��Aɽ�Սѥ�����!Ո�����M�����͔��ɔ�����������ȁ����ͥ�ɕ٥�܁ٕ�ͥ��́���ɕх�����ͥ�������ɕ�}����͕�̰������������э������ɕ�}����͕�̰�������ѕ�Ё�ո���х��ф��Y�ɥ�������չ�́����Ց���и�܀��а����ͥ����̀���������э���́�����и����ذ����ͥ����̀���İ������э���̸4(��1�ѕ�Ё�ɽ�Սѥ����ո��Ёٕɥ����ѥ����́����ش�Ĵ��|�����|��쁕����ٕ�ͥ�����́չ�ٕ�͔�ͥ销����������э�����	Ud���չ�́�����Ѡ�ͽ�ɍ�̸4(���͍ɥ��ٕ̽ɥ��}������͕}���ɽȹ�倁�́ɕ������丁%��Ʌ��䁍����́ѡ����ѕ�Ё�ո���ѕȁ���ɽȁ�幌쁑���䰁ݕ���䁅������Յ���幌���ͼ������ɔ�ɕх�����!��ѽ��ͥ����́������э���́��ѕȁɕѕ�ѥ����Ց�Ё�����ɔ��́٥ͥ������Ё�������������ͼ���!Ո�ɕ����́��ѡ�ɥхѥٔ���������������Ё�ɽ��M�����͔��م���������4(��Y�ɥ����ѥ���AML�A�ѡ��������������ɥ��͵����ѕ�а�e50����͔���Ȁ�́ݽɭ����̰����Ё����������������ձ�������ȁ����ո��͕��ɥ��ɕ٥�ܰ��ɽ�Սѥ����ձ���ե����ո������������Հ������ɕ��������ɽ�Սѥ���ME0��Ё��͠������ɥͽ���1�ɝ��Ё!��ѽ�䁙������ѕȁ��э������ɥ�����Ё�ܸ̀�؁5�������܁ѡ�����5��͕�٥����Յɐ�4(��Q����ɽ�Սѥ����ձ���ե����Չ��͡�����ф������Ё��݅����̀��Q�����܁��ɥ���ѕ����͕���ݥ�������Ё�ᕍ�є����ѡ�����Ё���Ʌ��佑����ݕ���併��Յ�����ɽȁݽɭ����쁹�����Յ��ɕѕ�ѥ���ݽɭ���܁݅́�ɥ���ɕ����ɥ���ѡ�ٕ́ɥ����ѥ���4(4(���Y9Mѽ���ݽɭ���܁�������х�����䀠���ش�Ĵ�Ԥ4(4(��%��Ʌ����չ́��ѕɹ�ѕ�����ݕ����Ս���́�������������́ݡ������!Ո�ɽ�������Ё�ݼ�U�չ�Ԁ�ظ�Ё�չ��ȁ�����̸����ѥ��͕̽������ѡ����ɕͽ�ٕ���̸�ŀ�Ѽ�̸�ĸ�܁���ѡ����������������̸�ĸ�����ѡ����܁������4(��Q���������������䁥���Ց���ѡ�Ё͕����A�ѡ�����э���ٕ��ѡ�՝��ѡ���������Y9Mѽ�����٥ɽ����Ё�ݹ́�������ɕ�ЁA�ѡ���չ��ȁ����нٹ�ѽ����ٕ�ـ��Iչ́���̸�ĸ��ѡ�ɕ��ɔ���ձ����Ё͕��ѡ���������ɕ�ѕ��ݥѠ�ѡ��̸�ĸ�܁���4(�����䰁���Ʌ��䰁XЁ����������ݕ���䰁���������M�����͔��幌���܁���ѡ��Y9Mѽ�����������U�չ�ԁٕ�ͥ�����չ��ȁ�ɍ��ѕ���ɔ������%M<�ݕ����Q��䁍������Ʌє�ѡ���ɥ�ȁͅ���U�չ�ԁ�ԁA�ѡ�����э��������4(��]������ո������������倁ɕ�ѽɕ��ѡ��������=L������ѥ���Ё��������Ё��ٕ́�؁�������ݥѠ���Ѐ��܁���U�չ�Ԁ�ظ�]����䁹�܁����յ�́ѡ��ͅ��������ѥ�����ԁ�������́����䁅������Ʌ���4(������M�����͔��幌��չ́�����������������������������ɀ�����������ѡ��=!1��ѕ����ѕȁ�����ѥ������չѕ�ѕ���������Ёٕ�ظ�Q���ݽɭ���܁��܁�ᕍ�ѕ́��������Ё�ɽ�������ɔ�͕���ѥ���ѡ����������չѥ�����������́�����Ѽ�͕����A�ѡ���ݡ���ѡ���ɽ�������̸4(������ɕ�ե��́����ݡ�����́�������Ё��٥ɽ����Ёم����ѥ�������̰�ͼ���م�������Ʌѕ���������́��Ё��͍�ɑ�����ɕ�䁉����͔�ѡ���ɥ���䁭��݅́�����ѥ�����э��4(��Y�ɥ����ѥ��聅����́ݽɭ���܁e50�����́���͔��ѡ����ٔ��ɽ�Սѥ��������������́�͔�ѡ���х������䁅������Ʌѥ����ɕ��ఁ���Ё�����������������͕̰�����ѡ��ݽɭ���͕ܽ��ɥ��ɕ٥�܁��չ�������܁͕�ɕЁ�ȁ��ɵ��ͥ���������ɔ�4(4(���Y9Mѽ�������Ʌѥ���؁��͡���ɐ�ͽ�ɍ������ش�Ĵ��4(4(���ٹ�ѽ��ـ��́��ѡ�ɐ��ݹ�ȵ͕���х������͡���ɐ�ͽ�ɍ����ͥ���M�����͔�������!Ո��Q���䰁	�䰁!��ѽ�䰁����̰ͥ�����̰����ѽ�䁑�х��������%�����ɽ�є�ѡɽ՝��ѡ������Ʌѥ���؁����ѕȸ4(��Q������ɕ�Ё͕�٥���������́�������ѱ䁁�ɥ��������Ё��ѥٔ�͍�ɥ��聍��ɕ�Ё��!Ո�͍�ɥ�����ф��́���ѕɕ��Ѽ�ѡ��İ��ܵ�嵉���MM$�����Ʌѥ���؁չ�ٕ�͔��%������������ѥ�́ɕ���������ɕ������ɕ��є�م�Օ̸�ٕ����؁�����͡��́ѡ�́�ɽٕ��������������́Ѽ���ٹ�ѽ��ـ쁅����م�����ȁ���ͥ����������Ё����́٥ͥ���ݥѡ��Ё��ͥ���Ё���������4(��������нٹ�ѽ��ص�ɕ٥�ܽ��͡���ɐ��ͽ����́ѡ���Չ��͡�������Ʌ�и�%Ёɕ��ɑ́��������ͽ�ɍ���ɽٕ�������ѡ��������є�ͽ�ѕ��MM$��嵉���չ�ٕ�͔������Ё��͡���ɐ���������ѥ�̰������х����х��̸��ѡ��ѥ��ѥ�������MM$�ɕ��ɕ������͍�ٕ�䁅ɔ���ѥٔ������Ս���͙հ쁹�ѥٔ���ɭ�Ё�����ѥ�������͍�ɥ����ɔ���������͕�٥����́�Ս���͙հ�����ɥ���������4(��Q�������������Ёхɝ�Ё�́������н͕�٥���ٹ�ѽ��ؽ���ɕ�р��ݥѠ�͕��Ʌє���٥ɽ����н��������������ЁMM$�����̰����������́�ɽ��ѡ������Y9Mѽ����չѥ�������͕�ɕ�́�����ѥ����̰���������ɽ��ѥ���չѥ����ѥٔ������а�͍�ɥ����͕�٥����������ɥ�䁍����́���̸�M�������̽ٹ�ѽ��ص���ܹ����4(��Aɽ�Սѥ�������Ʌ�Ёٕɥ����ѥ��聅������ɕ�Ё��͡���ɐ��嵉��́�������Ѽ�ѡ��MM$�չ�ٕ�͔����؁����͕̀����Q����ɽ�́��ȁɕ٥�ݕ��ٕ�ͥ���	�䁍�չ�̀�ļ�ܼ���!��ѽ�䁍�չ�̀�԰�����ܰ�������������ͥ́��չ�̀İ���Ȱ����Ȱ���쁅�����������Ё�嵉��́��ȁ�и�ܽ�и���и��͡���܁ɕ����ѥٕ�丁Q����ɥ����%���屽������х��̀��Ё���ɥ�̰���������ѽ�̰��������ѽȵٕ�ͥ���ɽ�̰�������ɝ�����ɽ�̰�����İ��ȁ��������ɽ�̸4(��Y�ɥ����ѥ���AML�A�ѡ�������Ʌ�Ё�ե���ȁ����م����ѽȰ�����ѥٔ�͕�ɕе������م����ѥ����Q���M�ɥ�а�M1��а�9��й�́�ɽ�Սѥ����ե�������Ё�����������������Ѡ���չ���䁍����̰�����͕��ɥ��ɕ٥�ܸ���!Ո��ѥ��́�չ́�����������ـ��ݕ���Յ���䤁���������������ŀ����؁�����ɥͽ���Չ��͠�ɕم����ѥ�����Ս���������ф������Ё��������Հ�݅́�Չ��͡��������Y�ɍ��������嵕�Ё����|���	�-I�	��QѭU1 ��i�e1���eM���́Id�4(���ѡ��ѥ��ѕ��ɕ���ɕ��٥�Յ����ѕɅ�ѥ���݅́��Ё������ѕ�������͔�ѡ���ɽ�������ɽ���ɥ�������������ɥ�����٥��ѥ����I�����ͥٔ���������何�ɽȁ�хѕ́ݕɔ�ɕ٥�ݕ����������չ��ѡ��ѥ��ѕ��������ɕ��ɕ�Ё����ͽ�ɍ���ݥэ����ѡ�ɥ�ѥ���ݕɔ�ٕɥ�����4(4(���Y9Mѽ�������Ʌѥ���؁��ѥٔ���ф�����������ش�Ĵ�Ȥ4(4(����؁݅́���Ʌ�����ɽ��Iн=A$�I́Ѽ��������ٹ�ѽ����ظ����������ٹ�ѽ�����������ĸŀ�ѡ����ᕐ���!Ո��ѥ��́��٥�������ѥ�䁥́ɕ�͕��Ѽ��ٽ���������Ʌ���չ��ȁɕ����Ʌѥ��̸4(��M��ɍ���������ѥ���ո������������ŀ����͕��MM$�ɕ��ɕ����ɕ��ɹ���İ����嵉����MM$�����!M�=!1���Ѡ��Ս�������!M���������͡��а���������хѕ���Ё������͠����܁ɽ�ѕ́�Ս����������!Ո�͕�ɕЁ�%9!e}A%}-e���́����������䁅Ё�չѥ���Ѽ�ѡ��������ѽȁمɥ������!M}A%}-e��4(��9�ѥٔ��������є��ո������������Հ����͕������Ѽ�����ݥѠ����������嵉��̰�����͕�٥���ɽ�́���������������嵉��̸�5�ɭ�Ё�ɥ����݅́MM$�!M����������݅́��Ё��������]����Յ�����ո������������̀����͕��4(��9�ѥٔ��ɽ�Սѥ�����ф��ո������������ခ�Չ��͡��������Ё���ф噄ŀ聝���Ʌѥ���؁�����Ƚ�х��́������؁�ͽ��ѕ��͕�٥�����х͕�́չ��ȁ������н͕�٥���ٹ�ѽ��ؽ���ɕ�р��Q����Չ������͡���ɐ��������Ё������Ʌѕ��ɕ����́�������ɥ����쁹��Y�ɍ��������嵕�Ё�ȁ��͡���ɐ���ѥمѥ��������ɕ��4(���ٹ�ѽ���}��ѥٕ}�ɽ�Սѥ���嵱���́ѡ���ḽ���Յ�����������Ё��ȁ���Ʌ��佑����ݕ���䁵���́����͡�ɕ́ѡ���ٹ�ѽ���������ɥѕɀ����������ѥمѕ}��͡���ɑ������ձ�́Ѽ����͔��������Ё�х䁙��͔�չѥ��ѡ�������ѥ����ݕ��ɕ���͔��́�����啐�4(����ɕ�Ё��ظ����ѥٕ���́ѕ�����������丁!M��չ�����х��ɽ�ѕ́�ɔ�����Ѡ�͍������������������ɽٕ�������́ɕ��ɑ������Ё�չ�����х��م�Օ́�ɔ���Ё�Ё����Ց������͍�ɥ����%Ё�́��Ё�յ�ɥ����䁕�եم���ЁѼ��и���и��4(����Ʌ�ͥ��Ё!M���͠����܁���ݽɬ���ɽȁ���ѡ������Ё�ɽ�Սѥ����Չ��͠�݅́��������ݥѠ���չ����ɕ�ɥ�̸�Y�ɥ����ѥ����ո������������р��Չ��͡��������Ё�����ݘՀ�ݥѠ�����ѡɕ��!M��хѕ����́�Ս���͙հ������ѕ��Ѐā������չ�����х�}�х�����م������}���}͍�ɕ��쁑�͡���ɐ������ɕ���������ɥ�����4(4(������؁���Ʌ���ɕ�х�Ѐ���ش�Ĵ��4(4(���ٹ�ѽ���}��ѥٕ}�ɽ�Սѥ���嵱���́ѡ���������؁�ɥѕȁ���������Ё��ȁ�Ḹ�Q������յ��ѕ�����������́��ٔ�ݕ������ɥ����́����ͥ��!�}��}5���������԰�������������������ԁ����������4(��ٕ���Ս���͙հ��ո���э��́MM$�ݥѠ�!M������������Չ��͡�́ѡ���ͽ��ѕ�����؁�н͕�٥���ɕ���͔�����ɕم����ѕ́Y�ɍ����%��Ʌ����չ́�������ɥٕ��ݽɬ����ɕ���х�쁑����ݕ���䁵���́ɕ�ե����ձ��%������̸ͥ4(���ѥٔ�͍�ɕȁ�́��ظĵ�م��������倰�����ѕ���ɽ��ѡ���ɽ�Սѥ������ѽȁ����Ʌ�и�5��ͥ������ѽȁ�����́�ɔ�ɕ��ɑ�����ȁ�嵉��������፱Ց���ݥѠ�ݕ���Ёɕ��ɵ����ѥ���ѡ�䁅ɔ���ٕȁͥ���ѱ��ɕ�ѕ���́�ɼ��չ�����х�������ɽ�Ѡ�ɕ������፱Ց���չѥ����ȵ�嵉���!M���ɵ����ѥ�������̸4(���ḁݽɭ���܁�U���]]��-չ�I����Y9Mѽ�����؃
܁����ɽ�Սѥ���͍���ձ�̀���́�Չ��͡���������ѥٔ�����ͥ��!�}��}5������AՉ��͡���ٕ�ͥ�������ń�ш��͐�ё�е���д����ݑ��Ո�̀���́ѡɕ��͍���ձ���ɥ����́����ͥ������聙�ٔ�ݕ����䁥��Ʌ���ѥ��̰�ݕ����䁑���䁵���ѕ�������Ѐ����԰�����Mչ���ͱ�ܵͽ�ɍ��ɕ�ɕ͠��Ѐ����Ը���������э��́�͔�ѡ���ѽɕ�����!Ո�����չр��ɕ���ѥ��쁹��ѽ�����́������������ݽɭ���܁����̸4(��م��������䵅݅ɔ��������є��ո������������Հ����͕���Aɽ�Սѥ����ո������������倁���͕�������Չ��͡�����ф������Ё���Ս���ɀ�ݥѠ����������嵉��́�����ɼ���������嵉��̸4(��Q���͕�٥���ɕ���͔����х��̀������ظĵ�م��������倁ɽ�̸����ɽ�́�����ɔ���፱Ց�}���}ɕ��ɵ���镀쁙չ�����х�������ɽ�Ѡ�ݕɔ�չ�م���������ȁ͍�ɥ��������������ѱ䁕፱Ց����ɽ����������ɽ�̸4(��Y�ɍ��������Ё�х��́�́�Ս���͙հ�������ٹ�ѽ��ـ�ɕ�����̰���Ё����嵽�́ɕ�Օ��́ɕ��ɕ�ЁѼ���������쁅�ѡ��ѥ��ѕ��ɕ���ɕ����ф�ٕɥ����ѥ���ɕ����́��͕��Ʌє��ݹ�ȵ͕�ͥ���͵����ѕ�и4(4(������؁��ф�������������Ѐ���ش�Ĵ��4(4(�����؁��܁��́ѡɕ��͕ɥ���镐��ɥѕȁ�������́չ��ȁѡ��͡�ɕ��ٹ�ѽ���������ɥѕȁ������ɕ��䁝ɽ���4(��Q����ḁݽɭ���܁�́ɕ����ͥ������ȁ�����ɽ�Սѥ���͍���ձ�̸�%�́��ٔ�ݕ����䁥��Ʌ��䁑����э��́ɕ������䁵�ɭ�Ё=!1X������ձ�ѕ́ѕ��������͍�ɥ��������а��Չ��͡�͕́�٥�����ф�����ɕم����ѕ́Y�ɍ���4(����ѥ���=!1����ѽ�䁥́��ɝ����ɽ�����е��䁍��ɕ�ѥ���ݥ�����ѡ���������ɕ�Օ�Ё�́�͕������ݡ������嵉�����́������������ѽ��4(��%��Ʌ��䁹�������ȁ����́!M���������͡��а���������хѕ���Ё�ȁ��͠����܁��������́������������ȁ�م�Յѕ́�ٕ�䁡��ѽɥ������э������ٔ�ѥ��́��ȁ���4(���ḁ�����э��́ٹ�ѽ���}�����}����ѕ������嵰��Ѐ����ԁ%P����ݕ�����̸�	���ɔ���э���̽%������̰ͥ��Ё�����́ѡ�������䁅���ѥٔ�	Q�QQ0��́���́�����ɹ���́���ѡ̰��ѡ��ݥ͔�������̤��ɕ�ɕ͡�́�����х������ͥ���!M��嵉��̰��ɕ͕�ٕ́���е���ݸ���������ɥ�́��������ɔ��ѡ���������́����ɕم����ѕ́Y�ɍ���4(���ḁ�����э��́ٹ�ѽ���}�չ�����х�}ɕ�ɕ͠�嵰��Ѐ����ԁ%P����Mչ���̸�%Ёɕ�ɕ͡�́MM$�ɕ��ɕ����������͡�������!M��хѕ����̰�����ձ�ѕ́ٹ�ѽ��}�Յ�й���Ʌѥ�̽�ɽ�Ѡ��م����ѕ͕́�ɕе�ɕ����ѥ����́����������́ѡ��������4(�����������嵉���ɕ�ɕ͠��ɕ͕�ٕ́ѡ�����Ё�Ս���͙հ�����������丁��ɥ�́����ȁѡ���ѡ����ѥٔ�̼������QQ0��ɔ��፱Ց����ɽ��չ�����х��ɽ�Ѡ�ݥѠ�ݕ���Ёɕ��ɵ����ѥ�������ѡ��ɕ�ͽ���չ�����х�}�����}�х���4(��Q����������є�ݽɭ���܁�ɽ��́ѡ��͕��Ʌѕ���չ�����х����Ѡ�ݥѠ�ѡɕ���嵉��́����ɔ���ɭ�н͍�ɥ����%Ё���ɕ���Ё�AMM}I�����䁅�ѕȁٕɥ�她��չ�م��������չ�����х���ɽ�Ѡ����ѽ�́�ɔ��፱Ց�������ݕ����́ɕ��ɵ���镐�ѡ��ݕ����ݽɭ���܁ɕ����́ѡ����ɐ��ɕ͡���́��є�4(��1�����ٕɥ����ѥ���A�ѡ�����������AML�ͥ�����͕��չ�Ёѕ��́AML���ѕȁɕ�ɥ�́�ɽչ��ѡ�����ݸ���ѕɵ��ѕ�Ё]�����́��ѥٔ��ɽ���́�Ʌ͠쁝�Ё�������������AML��M���ɥ��ɕ٥�܁��չ�����������ѕ��͕�ɕа������Ё������ɔ��ȁ��܁��ѡ�ɥ�ѥ�����չ����4(��Aɽ�Սѥ���������Ʌ���ո�����������ā�Ս������������Չ��͡��������Ё����͈݄�!M�ٹ�ѽ��}�Յ�Ё����������������ظȵ�Յ�Ё͕�٥�����������������������ɕ����э���̸�Q�������Ё���е����Ё���Ʌ����ո��������������ͼ��Ս�������ݥѡ��Ё��	Q�ɕ�ɕ͠�4(��������є��ո�����������؁���͕�����1�����MM$�=!1X����������!M�ɕ�ɕ͠�ͅ�����̼̰���Ё�չ�����х���ɽ�Ѡ�͍�ɕ��ɽ�́�����؁�م��������䁕፱�ͥ��̸����Ё͍���ձ��������ݕ�����չ́������ѡ��ѥ��ѕ����͡���ɐ�ɕ٥�܁ɕ��������Ʌѥ����������́������̽Y9MQ=,�}QM-L����4(4(������؁����ѥٔ�ͱ�ܵ��ф�ɕ�ɕ͠�������ش�Ĵ��4(4(���ٔ��ḁ���Ʌ����ɥ����́ɕ�����=!1X�����ͼ���ͱ�܁!M�ɕ�ɕ͠������Ё�������ȁ������͔�ѡ����ɭ�е͕�ͥ�����������4(�����䁵���ѕ�������Ѐ����ԁ%P���܁�չ́�չ�����х�̀���х�������聙ɕ͠�����������́�ɼ�ͽ�ɍ�������쁽����х������ͥ����嵉��́��э��	Q�����ɕ����ձ�є�ٹ�ѽ��}�Յ�й���4(��Q���QQ0���э��́�ɽ���ȸ��́���́�����ɹ���́���ѡ̀ļȼмԼܼ�����İ�������́�ѡ��ݥ͔��Mչ���ݕ����ɕ����́���ձ��ɕ�ɕ͠�ͅ���䁹�и4(��������є�م����ѥ�����������ȁ�ɕ��́�����͕�Ёɕ�ɕ͠��х��́������́����ф������ɔ�ݡ���͕�٥���ɽ�́���х���م��������ձ�ѕ�����ѽ�̸�5��ͥ����х������ѽ�́�ѥ������Ё����፱Ց�������ݕ����́ɕ��ɵ���镐�4(��Y�ɥ����ѥ������͕��A�ѡ������������)M=8����͔�����������͕��ѕ��́������Ё�������������!Ո�������ո��������������͕��ѡ���ɕ͠���������Ѡ������!M�����̤������ѕ��������э���̰��Չ��͡��������Ѐ������Ё����ɕم����ѕ��Y�ɍ����������є��ո�����������́ɕ�ɕ͡���!M�̼̰������ѕ��MM$�=!1X�������������ɕ��ɹ���AML��M���ɥ��ɕ٥�܁��չ��͕�ɕ�́ɕ�������!Ո�͕�ٕȵͥ������䁅����х��̽��������ѥ����́���х�������ɕ���ѥ���م�Օ̸4(4(������؁�ḁ͍���ձ����ѽٕȀ���ش�Ĵ��4(4(���ḁݽɭ���܁�U���]]��-չ�I���́ѡ��ͥ�����͍���ձ���ݹ�ȸ��ѥٔ�ٕ�ͥ�������ń�ш��͐�ё�е���д����ݑ��Ո�̀����х��́ѡɕ��͍���ձ���ɥ����́����ͥ�����́����ͥ��!�}��}5�����4(����!Ո�ݽɭ����́�ٹ�ѽ���}�����}����ѕ������嵱�������ٹ�ѽ���}�չ�����х�}ɕ�ɕ͠�嵱���ɔ�ݽɭ���ܵ�����э�����丁Q���ȁ��ѥٔ���!Ո��ɽ��͍���ձ�́ݕɔ�ɕ��ٕ��Ѽ��ɕٕ�Ё�������є��ɥѕ�̸4(����������э������́�͔�ѡ�����ѥ����ḁ��!Ո��ɕ���ѥ����I���ͥѽ�䁙���́����ݽɭ���܁)M=8����х������A$���䁽ȁѽ����م�Ք�4(������؁��͡���ɐ��ɕ͡���́������ش�Ĵ��4(4(�������ͥ́��չ��ѡ���нY�ɍ���ɕ���͔�݅́���ɕ�Ѐ����������P������i����ո������������ـ����Ёѡ����ѥٔ������ȁ�ѥ����͕���ͥ����}��є����ش�Ĵ�ɀ�ѡ����ٔ����Ʌ����չ́������������=!1X����丁Q�����ٹ�ѽ��ـ�����������ͼ�������啐�ѡ��͕��Ʌє����ش�Ĵ�䁍����ɥͽ��͹��͡�а�����Q����݅́��ɐ�������Ѽ�ѡ��ѡɕ���Ёٕ�ͥ��̸4(��%��Ʌ����ɽ�Սѥ�����܁ɕ�Օ��̀Ե����є�=!1X��ɽ��MM$�ݥѠ�!M��������������ɕ��ѕ́ѡ�͔����́��Ѽ�ѡ�����ɕ�Ё���ѥ�������䁍�������ѡ�������ձ�ѕ́�ظȸ�����ݕ���䁵���́ɕх��������=!1X����������Ё�������Ʌ��䁍���̸4(��Q���Q���䁉��ɐ���܁������́ѡ��ٕ�ͥ��́����͕����ѡ��͕���ѕ��ͽ�ɍ����؁�͕́��́�م���������ѥٔ��؁ٕ�ͥ��́ݡ����M�����͔���!Ո������ѡ���Ё�����ɥͽ��͕и���ٹ�ѽ��ـ������́��ѥٔ�ɕ���͔�ѥ������������ɥͽ��͹��͡�Ёѥ���͕��Ʌѕ��4(��1�����ٕɥ����ѥ���A�ѡ�������������������͕�����������͍�ɥ����Յ�Ёѕ��̰���Ё������������I���Ё�хѥ��ɕ٥�܁����͕��ɥ��ɕ٥�܁AML��9���ɕ���ѥ������ѡ�ɥ�ѥ�����չ���䁽ȁ���������䁍��������1�����ݕ�����н�����������ե���ɕ����́չٕɥ����������͔�ѡ������ɕ������݅́չɕ����������!Ո�Y�ɍ���$��́ѡ��ɕ�եɕ��ɕ���͔���є�4
## Gen6 source and cadence correction 2026-11-16

- Approved source boundary: SSI is the only reference/OHLCV source. FHSC is used only for quarterly financial statements (BCTC); it is not an intraday market fallback.
- Intraday executor is SSI-only and calculates/publishes ADX(14), Supertrend(10,3), `s_trend_st` and cached fundamental factors. Unsupported flow/depth fields remain unavailable and are excluded/renormalized.
- Post-market daily maintenance checks all FHSC statement sets by deterministic content signature, recalculates only changed BCTC factors, calculates the SSI closing score, then rebuilds outcomes/analytics/serving.
- Weekly fundamentals remain a full-universe recalculation safety net.
- Dashboard serving exposes ADX, Supertrend and BCTC cash-flow score/raw metrics; no credential value is stored in repository output.
- Local verification: Python compile and 17 Gen6 unit tests passed; 7 Gen6 workflow YAML files parsed; ESLint, TypeScript and Next.js 15 production build passed in an isolated temporary dependency workspace.
- Operational verification completed: candidate run `43800525885` passed; SSI-only intraday run `43801166361` completed in 2m25s, published 100/100 symbols for 2026-11-16, and revalidated Vercel successfully. Latest v6.4.18 snapshot has ADX/Supertrend/`s_trend_st` for 100/100, cached fundamental/growth for 56/100, and no `s_cf_core` until the post-market BCTC check runs.
## Gen6 parity indicators and slow-data cadence 2026-11-16

- Cron 2.0 registry comparison confirms the Gen6 production contract has 17 active signals. The four previously missing signals are `s_of_phasefix`, `s_prop_5d`, `s_insider`, and `s_cf_core`; the existing 13 formulas remain unchanged.
- `s_cf_core` now restores from the current audited `output/finance/cache.json` only when the native Gen6 cash-flow value is absent. Intraday never fetches BCTC. Verified local coverage is 100/100 symbols.
- `s_of_phasefix` uses SSI cumulative OHLCV and the exact cron 2.0 session-fraction anchors/bands. It adds no external intraday endpoint. Verified local coverage is 100/100.
- `s_prop_5d` and `s_insider` reuse the existing cron 2.0 scoring bands. Intraday reads the last-known-good FHSC cache; only post-market daily maintenance calls `proprietary_flow` and `insider_deal`. Verified cached coverage is 99/100 and 74/100; missing values remain null and are excluded/renormalized.
- Daily maintenance runs `run --refresh-slow-market`; the five intraday runs do not use that flag. Weekly BCTC remains a safety-net full refresh.
- vnstock 6.0.0 documents and exposes `Market("fhsc").equity(...).insider_deal()`, but omits `market.equity.insider_deal` from `sources.readers()`. Config validation carries a narrowly scoped metadata exception for that route only.
- Local verification: Python compile passed; 27 Gen6 unit tests passed; config/reader validation passed; cache-only full-universe scoring produced `s_cf_core` 100/100, `s_of_phasefix` 100/100, `s_prop_5d` 99/100, and `s_insider` 74/100.
- Security review found no committed credential value, client-side secret exposure, new dependency, or broadened external-source boundary. Workflow continues to consume GitHub secrets only through server-side environment variables.

## Gen6 parity production verification 2026-11-16

- Daily maintenance run `43829682476` completed successfully and refreshed the committed Gen6 fundamental cache before the production rerun.
- Workflow writer synchronization was fixed in commit `5d85011f`: queued daily/intraday jobs now sync the latest serialized `main` state, and production publishes `output/market/vnindex.json` with the rest of its ledger.
- Production run `43846935042` completed successfully, published data commit `4e9aba3b`, and revalidated the Vercel dashboard cache.
- Latest v6.4.18 snapshot is `2026-11-16 17:14` ICT for 100 symbols. Coverage is `s_cf_core` 100, `s_of_phasefix` 100, `s_prop_5d` 99, `s_insider` 74, `s_ff_net` 100, and `s_depth_wall` 46. Missing source values remain null and are excluded/renormalized.
- Native status reports 38 cash-flow overlays, so 62 symbols use native Gen6 BCTC cash-flow values and 38 use the audited legacy finance cache fallback. Intraday did not fetch BCTC.
- Browser interaction was not executed end-to-end: the in-app browser redirected to login and the already-authenticated Chrome tab could not expose DOM control. GitHub Actions publish/revalidation and committed serving data were verified directly.

## Gen6 dashboard completeness and quality gate 2026-11-17

- The approved source/cadence boundary remains unchanged: SSI supplies OHLCV, session aggregates and foreign flow; FHSC supplies order book plus post-market slow data. Intraday never fetches BCTC.
- `adtv_bil` again matches the cron 2.0 dashboard contract: current/last-session turnover in billion VND. The 20-session mean is preserved separately as `adtv_20d_bil`.
- The Buy tab receives `ff_intra_net` from the latest foreign-flow session, shows KN and liquidity with two decimals, and exposes the 20-session turnover in the liquidity tooltip.
- Post-market/daily runs no longer call order-book/session-depth endpoints. They reuse the most complete valid 09:00–15:00 depth snapshot for the same signal date, preventing a thin post-close book from overwriting in-session coverage.
- Candidate validation now writes `output/vnstock6/data-quality.json` and blocks publication for insufficient price, turnover, foreign-net or depth coverage, or invalid indicator ranges.
- Verification before deployment: 33 Gen6 Python tests passed; Buy-tab ESLint and TypeScript passed; Next.js 15 production build passed in the isolated dependency workspace. Production workflow/deployment verification is recorded after the remote run completes.
- Daily maintenance exposes `refresh_slow_data` (default `true`) so scheduled post-market runs still check BCTC/FHSC slow data, while an explicitly dispatched cached-data recovery can publish without violating the no-BCTC-before/intraday rule.
- Daily-close records use the stable `23:59` EOD marker for their `signal_date`; this prevents a next-morning recovery timestamp from sorting behind an older post-close snapshot. Intraday records continue to use their actual snapshot time.
- Production verification completed: candidate quality-gate run `43995675314` passed, cached daily recovery run `43996196508` passed, published data commit `f38d02fd`, and completed the Vercel cache revalidation step successfully without refreshing BCTC/slow data.
- Current Buy serving coverage is complete for the requested dashboard fields: v6.4.17 has 20/20, v6.4.18 has 39/39, and v6.4.19-shadow has 44/44 rows with session turnover (`adtv_bil`), 20-session turnover (`adtv_20d_bil`), KN/foreign net and depth. Every selected row uses the daily-close `23:59` marker.
- Data-contract checks found zero turnover-contract mismatches, zero foreign-ratio mismatches and zero invalid numeric values. The generated quality report is `PASS` with 1,800 rows and no low-coverage or invalid-value findings.
- Vercel production deployment `dpl_436waBNgDTEfZJKrWk172bhMAosQ` is READY on UI commit `26109c24`; later Python/data-only commits were intentionally canceled by the Vercel build-ignore policy and are consumed at runtime from GitHub serving after cache revalidation. Browser visual verification remains login-gated.

## Gen6 source-state, provenance và weekly material refresh — 2026-11-17

- Công thức 17 tín hiệu và ranh giới nguồn/cadence không đổi: intraday không gọi BCTC, proprietary-flow hoặc insider; daily hậu phiên refresh slow data; weekly là full-universe BCTC safety net.
- `s_prop_5d` và `s_insider` giữ last-known-good score khi FHSC trả rỗng/lỗi, đồng thời lưu status phân biệt `available`, `empty_response_unverified`, `unclassified_response`, `source_error` và `not_available`; không quy thiếu dữ liệu thành 0.
- Serving breakdown giữ raw values, source/as-of và checked/refreshed timestamps cho proprietary, insider, foreign, order-book/order-flow và cash flow. Buy/Today hiển thị lý do factor bị loại khỏi điểm khi nguồn không khả dụng.
- Weekly fundamentals so sánh nội dung BCTC/factor sau khi bỏ timestamp/metadata biến động. Chỉ khi có thay đổi vật chất mới chạy lại score, serving validation và Vercel revalidation.
- Production snapshot đã kiểm tra trực tiếp sau run `44014755975`: `2026-11-17 11:06` ICT, 100/100 VN100, quality gate PASS; coverage `s_cf_core` 100, `s_of_phasefix` 100, `s_prop_5d` 99, `s_insider` 74, `s_ff_net` 100 và `s_depth_wall` 85.
- Xác minh local trên HEAD sau khi merge JSON-safe: 43 Gen6 Python tests PASS, workflow YAML parse PASS, TypeScript PASS và Next.js 15 production build PASS. ESLint standalone bị chặn bởi local `node_modules` thiếu transitive module `debug`; Next build vẫn compile/typecheck và hoàn tất artifact production.
- Security review: không thêm secret/dependency/client credential, không mở rộng route dữ liệu, và workflow chỉ đọc GitHub secrets qua biến môi trường server-side.

## Gen6 timestamp and market-value integrity - 2026-11-17

- Gen6 accepts SSI/FHSC market observations only when their source date matches `signal_date`; stale foreign-flow, turnover and depth values are not scored as current-session data.
- SSI `session_stats` is queried for both intraday and post-market scoring. Its cumulative `total_value` is the preferred exact session turnover; OHLCV close-times-volume remains an explicitly labelled `SSI_OHLCV_ESTIMATE` fallback only when the exact aggregate is unavailable.
- Same-day SSI `session_stats` foreign buy/sell/net totals can align the current foreign-flow signal when the daily `foreign_flow` history has not yet published the session row. SSI remains first priority; FHSC remains fallback.
- Every new result carries actual `snapshot_at`, `run_kind` and `data_as_of`. Intraday uses the actual collection time; post-market uses the market close data boundary `15:00` while retaining the actual execution timestamp.
- Serving selection prefers timestamped Gen6 runs over legacy synthetic `23:59` rows on the same day and removes those old markers once a real timestamped run exists.
- Candidate validation checks only the latest snapshot for each scoring version and enforces same-date provenance for non-null foreign, exact-turnover and depth signals. Missing/unverifiable factors stay null and are excluded/renormalized.
- Dashboard labels distinguish exact current-session turnover (`GTGD phien`) from the 20-session mean (`GTGD TB20`); displayed values remain rounded to two decimals.
- Verification: 52 Gen6 Python unit tests passed; modified Python files compiled; TypeScript and Next.js 15 production build passed for the UI diff. Standalone ESLint remains blocked by the pre-existing local missing transitive `debug` module, while the Next production build completed.
- Unit tests mock the `vnstock_quant.ta.compute` boundary and no longer consume the Community daily calculation quota.
- Live diagnosis confirmed the Community account limit `QUANT_TRIAL_EXHAUSTED` at 30 calculations/day. The production calculation approach has not been changed; a quota-safe engine policy requires explicit approval.
- Security review found no credential value, new dependency, client-side secret, widened source boundary or unvalidated external write in this change set.
- GitHub account enforcement is now part of candidate, production and daily workflows. `scripts/verify_vnstock_account.py` logs in server-side and fails unless the authenticated vnstock tier is Silver or higher; it never prints the API key. Candidate run `44125082575` passed this check and the expanded quantitative-indicator quality gate.
- Code commit `bd80289e` was pushed to `main`. Vercel production deployment `7859293089` completed successfully for that commit, and the production alias remains `https://trading-snapshot-dl.vercel.app`.
- Production run `44126170926` completed successfully in 8m01s. Build/validation, Git-ledger publication and Vercel cache revalidation all passed; data commit `c54a6786` was published.
- The resulting 2026-11-17 23:35 ICT snapshot contains 300 serving rows (100 symbols x 3 scoring versions), zero invalid values and no low-coverage quality finding. Across all versions, price, turnover, foreign net, EMA20/50/200, RSI14, ATR14 and OBV cover 300/300 rows; depth covers 255/300 (85/100 symbols in each version) and missing depth remains excluded/renormalized.
- This run executed after market close, so it verifies final-session data collection through the intraday path, not live in-session movement. A true live intraday test requires the next scheduled trigger during a trading session; based on this run, allow about 8-10 minutes after the trigger for Git publication and Vercel revalidation.

## Gen6 indicator evidence display - 2026-11-18

- Dashboard indicator rows now follow score -> indicator -> signal -> actual input: depth shows bid/ask volume, price and ratio; growth shows revenue/profit YoY; market context shows regime and VN-Index/EMA values; fundamentals show the ratios used.
- UI no longer presents order-book source labels, proprietary/insider as-of dates, or order-flow collection timestamps as indicator evidence. Provenance remains in the serving/ledger payload for audit.
- Scoring formulas and source priority are unchanged. Daily preserves only same-session cached order-book inputs; a temporary empty intraday response can reuse only that same-day cache.
- Existing fundamental cache is backfilled with raw growth inputs on the next post-market BCTC maintenance even when the statement signature is unchanged.
- Verification: Python compile passed; 27 focused tests passed; 39 integration tests passed with one additional pipeline writer test blocked by the local Windows temp-directory sandbox; TypeScript passed; Next.js production build passed with lint disabled because the pre-existing local pnpm tree lacks the transitive `debug` module.
- Security review: no new endpoint, dependency, credential field, client-side secret or write authority was introduced; only already-public numeric market/fundamental inputs are added to serving output.
## Gen6 first-intraday depth provenance fix - 2026-11-18

- Root cause of production failures `44211603189` and `44223082513`: the first live FHSC order book of a new trading day was scored before `depth_signal_date` was advanced from the prior-day cache, so the temporal quality gate correctly rejected publication.
- Live FHSC order-book metadata is now stamped with the current signal date, snapshot time and capture timestamp before scoring. `FHSC_SESSION_CACHE` is deliberately not restamped, preventing stale depth from being presented as current.
- Scoring formulas, thresholds, source priority and cadence are unchanged.
- Verification: Python compile passed; 24 focused tests passed; the broader suite passed 45 logic tests with one pre-existing local Windows temp-directory sandbox error. Security review found no new credential exposure, endpoint, dependency or authority change.