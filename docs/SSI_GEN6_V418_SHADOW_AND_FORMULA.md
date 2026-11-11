## Trạng thái nghiệm thu lúc 11/11/2026

- [SSI PR #43](https://github.com/vn99instrumental-web/ssi-data-pipeline/pull/43) **MERGED** (`37b49009aab894b56b0d339d0b47711a099b9c05`), toàn bộ **370/370 tests PASS**.
- [VNStock PR #50](https://github.com/vn99instrumental-web/vnstock-cron-v2.0/pull/50) **MERGED** (`607a1e0f87b431be00fb4cec9f9078c0342ee10a`), [web lint, typecheck, build #42992918298](https://github.com/vn99instrumental-web/vnstock-cron-v2.0/actions/runs/42992918298) **PASS**. Shadow JSON trên hai repo có cùng Git blob SHA `01f850081817f78963e51a8e1620a3f8ce6d08cd`.
- **CHƯA live trên Vercel production**: tool authenticated deploy `trading-web` project ID `prj_wisfNIVNrS6et4U9RsAl5O2cBEKt`, target production, GitHub main SHA chính xác đã bị Vercel trả HTTP **402 payment_required: api-deployments-free-per-day** (Hobby >100 lượt/ngày; response retryAfter 86400 giây). Không thay đổi gói/billing. Deployment READY được quan sát cuối vẫn dùng code cũ SHA `6550b80b58fa03653695a120ff3b7f2aa04fcbf8`.
- **Pending duy nhất để nhìn thấy Shadow trên web:** Khi quota được reset hoặc chủ tài khoản điều chỉnh gói hạn mức, deploy đúng commit `607a1e0f87b431be00fb4cec9f9078c0342ee10a`, xác minh trạng thái READY và `https://trading-snapshot-dl.vercel.app/vnstock6` hiển thị bảng 97 mã, chi tiết 17 signals, null missing. Chỉ xác nhận hoàn tất rollout sau kiểm nghiệm thực, không suy từ Git merge.
- Chưa có official Trade/Hold SSI hoặc BUY/SELL, dữ liệu source trade_date 09/11; trang phải ghi NOT FOR TRADING.

---

# SSI + Finhay Scoring v4.18 Shadow — Thế hệ 6 / Vercel

**Nguồn:** [SSI v4.18 shadow export](https://github.com/vn99instrumental-web/ssi-data-pipeline/blob/main/output/audit/ssi_v418_gen6_shadow.json) / [source PR #43](https://github.com/vn99instrumental-web/ssi-data-pipeline/pull/43).

**Phạm vi:** dùng chính `trading-web` Vercel và route `/vnstock6`. Không thêm Vercel mới, không thay tabs Mua/Hôm nay, không thay production scoring v4.18/v4.19, không gửi Zalo, không SSI V2.

## Đã xây

- `web/data/ssi-v418-gen6-shadow.json`: copy byte-for-byte nguồn real stored SSI EOD 09/11/2026, **97 mã**, **17 slot tín hiệu/mã**. **90 mã có 9 ứng viên**, 5 mã có 8, 2 mã 0; 0 mã có điểm chính thức.
- `web/lib/ssi-v418-shadow.ts`: fail-closed validation — pinned v4.18 reference, source trade date, tất cả signal statuses, cap ±span, null for missing, checksum contract flags, không có score/BUY/SELL được nhét từ ngoài.
- `web/components/ssi-v418-shadow-panel.tsx`: hiển thị danh sách lọc/sort/search; số điểm ứng viên, danh sách và lý do thiếu từng `signal_id`, đóng góp theo từng factor ở khung Trade/Hold trong giả định **SIDEWAYS**, có thể mở detail 17 tín hiệu. Các cột tổng điểm chính thức hiển thị **— (khóa)** và nhãn NOT FOR TRADING.
- `web/app/(dashboard)/vnstock6/page.tsx`: nhúng panel mới trên **Thế hệ 6**, giữ nguyên đối chiếu SSI v4.18 cũ và Gen6 bridge. Nếu dữ liệu không đạt đủ kiểm chứng thì thông báo rõ, **không fallback** sang điểm VNStock.
- Phần `scoring formula` gốc và cổng kiểm đầu vào đã nằm ở repo SSI `src/ssi_pipeline/v418_full_formula_gate.py`, gọi engine frozen v4.18 CHỈ khi đủ 17 tín hiệu + genuine regime, extras, PIT, nguồn đúng thời điểm, các bằng chứng parity. Dữ liệu thiếu thì không gọi scorer và không tính tổng.

## Giới hạn cần hiển thị nổi bật

- **Không coi đóng góp theo SIDEWAYS là score_trade**. SIDEWAYS chỉ giả định minh họa vì market regime chưa được chứng nhận.
- Các chỉ báo đã có ứng viên cũng **chưa được chứng nhận exact original-method parity**; không dùng làm BUY/SELL.
- 17 tín hiệu đều phải phân biệt `candidate_points: 0` (số 0 ứng viên thực) với `candidate_points: null` (thiếu/chưa đủ source). Không renormalize weights để "bù" signal còn thiếu.
- **Nguồn dữ liệu snapshot 09/11/2026, không realtime.** Finhay 20/97 mã đã thu source, 77 mã chưa có; việc nguồn tài chính được thu sau 09/11 không đủ historical PIT. Source v4.18 chưa full parity.
- Không tự tính lại external proprietary/insider/OF và không gán extras 0 khi chưa có nguồn.

## Kiểm thử và deploy

1. [SSI PR #43](https://github.com/vn99instrumental-web/ssi-data-pipeline/pull/43) full test/CI PASS, merge và kiểm dữ liệu main.
2. [VNStock web PR](https://github.com/vn99instrumental-web/vnstock-cron-v2.0/pulls) `web/**` CI: `npm ci`, `npm run lint`, `npm run typecheck`, `npm run build`; kiểm commit preview `trading-web` trên Vercel thật, ưu tiên route `/vnstock6`.
3. Sau merge vào VNStock main, kiểm tra latest Vercel deployment READY, route hiện cả bảng Shadow. Chưa phát hành chính thức BUY/SELL v4.18 từ SSI.
4. Lần cập nhật: sinh lại snapshot ở SSI sau khi dữ liệu mới được chứng nhận, mirror cả file đã kiểm vào VNStock PR rồi deploy. Nếu chưa có refresh, UI giữ ngày 09/11 để tránh nhầm realtime.

## Còn việc để nâng lên Full Scoring

- SSI 97 mã EOD cùng ngày, tương đương TA original; giá as-traded có xác minh điều chỉnh từ nhà cung cấp;
- Finhay issuer published_at/PIT, 77 mã còn thiếu; CFO period, D/E, growth ngân hàng/chứng khoán;
- Orderflow true trades size, buy/sell order count + ff_intra; self-dealing/insider; FHSC MCP OAuth;
- VN100 effective historical membership, AD và hysteresis; full same-input original v4.18 numerical parity + forward ledger.

Đây là một **bản dữ liệu và công thức shadow để hoàn thiện dần**, không phải engine giao dịch độc lập mới.
