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
