# Quy ước nguồn kỹ thuật cho phân tích cổ phiếu — Gen6

**Hiệu lực:** 2026-11-17  
**Phạm vi:** trợ lý/agent phân tích cổ phiếu Việt Nam khi tra cứu dữ liệu GitHub trong repo `vn99instrumental-web/vnstock-cron-v2.0`. Đây là **quy ước nguồn tham chiếu cho bài phân tích**, không phải thay đổi công thức tính score, cấu hình production của pipeline hoặc UI.

## 1. Ưu tiên Gen6, không dùng V4 làm kết quả hiện tại

- Khi người dùng đưa mã chứng khoán hoặc yêu cầu đánh giá cổ phiếu, lấy **tín hiệu Gen6 mới nhất đang có trên branch `main`**, thay vì `output/v2f_signals_v4.json` hay `output/v2f_trade_levels_v4.json`.
- Tại thời điểm ban hành, **cấu hình chính để phân tích kỹ thuật là `v6.4.18`**; `v6.4.19-shadow` chỉ dùng **đối chiếu/thử nghiệm**, không thay production; `v6.4.17` là góc nhìn đối chiếu khi cần.
- Với các lần phân tích tiếp theo, **kiểm tra `native-status.json` và `metadata.json` trong lần truy cập hiện tại** trước khi chọn version. Nếu production Gen6 được nâng cấp chính thức, chuyển theo version production được xác nhận; không khóa vĩnh viễn ở `v6.4.18`.
- **Không** tự tính lại hoặc bổ sung điểm Gen6; không hoán đổi score V4/V6, không dùng shadow thay production, không trộn điểm và trade levels từ những version khác nhau.
- V4 giữ lại **chỉ để nghiên cứu lịch sử** khi người dùng yêu cầu so sánh, không dùng để kết luận tín hiệu kỹ thuật hiện tại.

## 2. Đường dẫn chuẩn trên GitHub

Repo: `https://github.com/vn99instrumental-web/vnstock-cron-v2.0` — branch `main`.

| Vai trò | Đường dẫn tương đối |
| --- | --- |
| Xác nhận version, thời điểm phát hành, chất lượng nguồn | `output/vnstock6/native-status.json` |
| Metadata và run mới nhất theo version | `output/serving/vnstock6/current/metadata.json` |
| Kiểm tra release, provenance và dữ liệu đủ bộ | `output/serving/vnstock6/current/manifest.json` |
| Tín hiệu hiện tại theo version (ưu tiên khi đọc được) | `output/serving/vnstock6/current/today/<version>.json` |
| Lịch sử tín hiệu (chọn đúng run/date mới nhất) | `output/serving/vnstock6/current/history/<version>.json` |
| Tín hiệu BUY và factor breakdown chi tiết **chỉ cho mã xuất hiện trong danh sách BUY** | `output/serving/vnstock6/current/buy/<version>.json` |
| Tóm tắt tín hiệu và kết quả theo mã (không phải nguồn cho mọi indicator) | `output/serving/vnstock6/current/analysis/<version>.json` |
| Chuỗi giá và timeline của một mã | `output/serving/vnstock6/current/charts/<version>/<TICKER>.json` |
| Ledger raw Gen6 theo ngày, khi cần đối chiếu | `output/history/vnstock6/predictions/YYYY-MM-DD.jsonl` |

Lưu ý: `buy/<version>.json` chỉ chứa danh sách đủ điều kiện BUY; **không thấy mã ở đây không có nghĩa là SELL/NEUTRAL**. Với các mã đó, phải đọc nguồn `today`/`history` hoặc ledger. Khi một tệp bị giới hạn tải/không truy xuất được, ghi rõ hạn chế và kiểm tra nguồn tương đương **trong Gen6**; không âm thầm quay sang V4.

## 3. Quy trình bắt buộc cho từng mã

1. **Kiểm tra mới nhất**: lấy `native-status.json`, `metadata.json`, `manifest.json`; xác nhận `generation=6`, version chính thức, `market_factor_date`, `generated_at`, trạng thái chất lượng.
2. **Đọc đúng tín hiệu**: tìm `<TICKER>` thuộc **run mới nhất của version chính**, thu `score_trade`, `decision`, `confidence`, giá tham chiếu và ngày/timestamp. Nếu có, đọc `breakdown` từ đúng cùng prediction/run để chọn 3–5 indicator đáng chú ý.
3. **Kiểm tra chất lượng**: đọc `available_weight`, `fundamental_status`, tình trạng thiếu/stale factor. `confidence=HIGH` là độ tin cậy theo bộ chấm điểm, **không phải xác suất tăng giá hoặc thắng lệnh**.
4. **Phân biệt thời điểm**: ghi ngày thị trường của giá OHLCV và ngày phát hành snapshot; timestamp kỹ thuật `23:59` có thể là thời điểm đóng gói, **không mặc định là giá khớp lệnh 23:59**.
5. **Tách bốn lớp nhận định**: doanh nghiệp (báo cáo chính thức), định giá (giá/nguồn gần nhất), catalyst/risk (tin mới có ngày và nguồn), Gen6 (timing/trạng thái kỹ thuật). **Gen6 không được quyết định thay cho phân tích nền tảng.**
6. **Nếu Gen6 không truy xuất được**, ghi: “Không truy xuất được kết quả Gen6 hiện tại.” Tiếp tục phân tích doanh nghiệp/định giá/tin tức mà **không tự tạo dữ liệu kỹ thuật thay thế**.

## 4. Diễn giải kỹ thuật và trade levels

- Ưu tiên tối đa 3–5 tín hiệu quan trọng: RSI / Williams %R / Bollinger, EMA / Supertrend / ADX, thanh khoản và dòng tiền khi có chứng cứ.
- Dòng tiền mua/bán, ngoại, tự doanh, insider, độ sâu: chỉ nêu khi đúng nguồn Gen6 báo có dữ liệu; không biến chỉ số thiếu thành 0.
- `regime` nếu là trạng thái chung toàn thị trường thì **không dùng riêng nó để đánh giá sức khỏe một mã**.
- `entry`, `stop`, `tp1`, `tp2` chỉ lấy từ bản ghi Gen6 **cùng version và cùng phiên**, và chỉ nêu như mức tham khảo khi `decision` là `BUY`/`STRONG BUY`, kèm rủi ro/điều kiện. Không diễn giải trade levels như lời hứa giá đạt mục tiêu.
- Nếu sự kiện chia cổ tức, tách/gộp cổ phiếu hoặc corporate action xảy ra sau snapshot, kiểm tra điều chỉnh giá trước khi dùng các mốc kỹ thuật.
- Score giữa V4, Gen6 và giữa các profile có thể khác cấu trúc/chính sách thiếu dữ liệu; **không dùng phép trừ hai score để kết luận cổ phiếu tốt hơn/xấu đi**.

## 5. Format tóm tắt kết quả

| Mục | Nội dung bắt buộc |
| --- | --- |
| Tổng thể | TÍCH CỰC / THEO DÕI / THẬN TRỌNG; hành động BUY/CÂN NHẮC MUA, HOLD, WATCH, AVOID, GIẢM TỶ TRỌNG |
| Ngắn hạn / Trung hạn | Phân tích riêng theo thời gian |
| Định giá / Doanh nghiệp | Dữ liệu mới nhất, ngày và nguồn rõ ràng |
| **Gen6 — kỹ thuật tham khảo** | Version, run + snapshot, score_trade, decision, confidence, 3–5 tín hiệu, hạn chế |
| Catalyst / Risk | Sự kiện có chứng cứ, ngày, tác động, điều kiện làm luận điểm mất hiệu lực |

Giữ kết luận có điều kiện, chỉ rõ **mâu thuẫn tín hiệu** nếu doanh nghiệp/định giá khác chiều Gen6. Ưu tiên độ tin cậy của dữ liệu hơn số lượng chỉ báo.

## 6. Ghi chú kiểm chứng ban đầu

Ngày 2026-11-17, `native-status.json` ghi `scoring_version=v6.4.18`, `market_factor_date=2026-11-16`; `metadata.json` xác nhận cả ba profile `v6.4.18`, `v6.4.17`, `v6.4.19-shadow`. Đây chỉ là **mốc kiểm chứng khi ban hành**, không phải dữ liệu cố định cho những lần phân tích sau.
