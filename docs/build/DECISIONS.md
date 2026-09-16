# DECISIONS — Architecture Decision Records (ADR)

> Nhật ký quyết định kiến trúc, **append-only**. Mỗi ADR: bối cảnh · quyết định · lý do · hệ quả · trạng thái.
> Không xoá/sửa ADR cũ; nếu đảo quyết định → thêm ADR mới "Supersedes ADR-xxx".

**HEAD gốc khi khởi tạo:** `38de5bb` · **Ngày:** 2026-09-12

---

## ADR-001 — Supabase project dùng chung, prefix `v4_`, không đụng bảng app khác
- **Trạng thái:** ACCEPTED (2026-09-12)
- **Bối cảnh:** Project `mcaqnaomzoqgxccdgvls` chứa nhiều app của user: `vibe_space` (rooms/messages/playlists/backgrounds/poems), `qcvn_*`, `n8n_chat_histories`, `staging_table_b`. Advisory Supabase báo **critical**: 4 bảng (`qcvn_documents`, `qcvn_parameters_master`, `n8n_chat_histories`, `staging_table_b`) **tắt RLS** — phơi anon.
- **Quyết định:** App VNStock **chỉ** đọc/ghi bảng tiền tố `v4_*`. **Không** bật/sửa RLS hay policy bảng app khác. Cảnh báo RLS được **surface cho user**, không tự remediate.
- **Lý do:** Never-do #7 CLAUDE.md — bật RLS thiếu policy sẽ khoá app cũ của user. 4 bảng kia không thuộc app này.
- **Hệ quả:** App an toàn tách biệt. User tự quyết xử lý advisory RLS của app khác (SQL remediation có sẵn trong advisory nếu cần).

---

## ADR-002 — Schema `v4_outcomes` (wide vs long): **WIDE** (CLOSED ở E1)
- **Trạng thái:** ✅ ACCEPTED — chọn (A) WIDE, migration `0002_outcomes_wide.sql` đã apply (2026-09-12, E1)
- **Chốt:** WIDE. Evidence quyết định: 12.794 rows outcomes 2026-08 đều đủ 20 field (hình chữ nhật hoàn hảo), chỉ 1 `lens='trade'`. Migration 0001 (long) sai: không có cột `horizon` trong ledger + unique thiếu `snap_time` (5 snap/ngày sẽ đè). Migration 0002: cột `ret_1d/3d/5d/10d/mfe_pct/mae_pct/t0_close/n_bars/eval_date/lens...`, `unique(symbol,signal_date,snap_time,lens)`. E6 IC vẫn tính per-horizon từ cột wide.
- **Bối cảnh:** Migration `0001` định nghĩa `v4_outcomes(symbol, signal_date, horizon int, ret)` — mô hình **long** (mỗi horizon 1 row). Nhưng ledger thật (`v2f_outcomes_v4/2026-08.jsonl`, evidence đã đọc) lưu **wide**: 1 row/prediction chứa `ret_1d, ret_3d, ret_5d, ret_10d, mfe_pct, mae_pct` + `lens`, `scoring_version_effective`, `t0_close`, `n_bars`.
- **Lựa chọn:**
  - **(A) Đổi migration sang wide** (migration `0002`): cột `ret_1d/3d/5d/10d/mfe_pct/mae_pct/lens`. Sync 1-1 với ledger, ít bug, mất khả năng query generic theo `horizon`.
  - **(B) Giữ long, sync explode**: mỗi dòng ledger → 4 rows (mỗi horizon). Query IC theo horizon linh hoạt, nhưng sync phức tạp, dễ lệch, ghi nhiều row hơn.
- **Quyết định:** **Treo** tới E1. Lý do treo (user chốt): E0 không phụ thuộc bảng outcomes; quyết khi thực sự code sync để có full context (IC cần dạng nào ở E6).
- **Hệ quả:** E1 phải mở lại ADR này, chọn A/B, và (nếu A) viết migration `0002`. Không code sync outcomes trước khi ADR này CLOSED.
- **Định hướng sơ bộ (chưa chốt):** nghiêng A (wide) vì đơn giản + khớp ledger; E6 IC vẫn tính được per-horizon từ cột wide. Xác nhận ở E1.

---

## ADR-003 — Một nguồn chân lý cho scoring: Python, không reimplement bằng TS
- **Trạng thái:** ACCEPTED (2026-09-12)
- **Bối cảnh:** App cần "what-if" cho user thử đổi config trước promote. Cám dỗ: viết lại công thức chấm điểm/IC bằng TS để preview.
- **Quyết định:** Con số **chính thức** luôn từ Python pipeline. `lib/scoring/simulate.ts` chỉ **ước lượng**, mọi output dán nhãn "simulation — không phải điểm chính thức". IC "chính thức" tính bằng Python (E6), không bằng TS.
- **Lý do:** Golden rule #3 — tránh 2 nguồn chân lý lệch nhau. Forward outcomes (Python) mới quyết.
- **Hệ quả:** UI phải phân biệt rõ vùng "simulation" vs "official". Không dùng simulate.ts làm căn cứ promote; promote chỉ ghi config, forward mới validate.

---

## ADR-004 — Config-driven scorer qua `active.json` (E5), fallback registry, shadow-first
- **Trạng thái:** PROPOSED (2026-09-12) — **cần duyệt trước khi thực thi E5**
- **Bối cảnh:** Evidence: `steps/v2f_step_scoring_v4.py:64` hardcode `SCORING_VERSION="v4.17"`, import `FACTOR_WEIGHTS/GATE_VERSION/gate_for` từ `utils.v2f_registry`; **không** đọc config ngoài. Để app điều chỉnh weights/gates, scorer cần đọc `config/scoring/active.json`.
- **Quyết định (đề xuất):** Thêm loader đọc `active.json` (weights/gates/thresholds) với **fail-soft** → registry defaults khi thiếu/hỏng. Giữ nguyên math. Đổi số → **bump `SCORING_VERSION`** + reset forward bucket. Shadow-first ≥30 phiên trước promote.
- **Lý do:** Version-agnostic (rule #2) + shadow-first (rule #4). Fail-soft đảm bảo không có config vẫn chạy y hệt hiện tại.
- **Hệ quả:** E5 chạm production Python → **HỎI DUYỆT**, `py_compile`+AST validate, giao full-file. DoD: không `active.json` → output byte-identical hiện tại.

---

## ADR-005 — Promote server-only, secret không ra client
- **Trạng thái:** ACCEPTED (2026-09-12)
- **Bối cảnh:** Promote phải commit `active.json` vào repo (cần `GITHUB_TOKEN`) và ghi Supabase config (cần logic tin cậy).
- **Quyết định:** `app/api/promote/route.ts` chạy **server-only**. `SUPABASE_SERVICE_ROLE_KEY` + `GITHUB_TOKEN` chỉ ở Vercel env server. Client chỉ dùng anon/publishable key. Promote validate theo `config/scoring/schema.json` trước khi ghi. Chỉ authenticated được gọi.
- **Lý do:** Golden rule #7 bảo mật. Chống inject config tuỳ tiện.
- **Hệ quả:** E4 bắt buộc `security-review`. Không có đường nào để secret vào client bundle (verify bằng grep + review).

---

## ADR-007 — Auth = Supabase Auth đơn owner; public read
- **Trạng thái:** ACCEPTED (2026-09-12, grill vòng 2)
- **Bối cảnh:** Hành động nhạy cảm duy nhất là Config editor + Promote. Còn lại (signals/outcomes/ic) repo vốn public, không nhạy cảm.
- **Lựa chọn cân nhắc:** (A) Supabase Auth 1 owner; (B) không auth, Promote qua secret server; (C) MVP read-only chưa có Config/Promote.
- **Quyết định:** **(A)** — Supabase Auth đơn owner (email của anh, whitelist 1 email). Public read toàn bộ. `/config` + Promote chỉ sau login. Không RBAC nhiều vai, không cho đăng ký user mới.
- **Lý do:** Bảo vệ được cả UI editor lẫn API Promote bằng session thật; RLS `read v4_configs = authenticated` đã sẵn sàng khớp mô hình này. Đơn giản, không over-engineer.
- **Hệ quả:** E2 dựng Supabase Auth + middleware chặn `/config`/Promote khi chưa auth. E4 kiểm tra session server-side trước khi ghi. Cần cấu hình allowlist email owner (Supabase Auth settings / kiểm tra trong route).

---

## ADR-008 — Sync chạy qua step non-blocking append vào cron workflow cũ
- **Trạng thái:** ACCEPTED (2026-09-12, grill vòng 2) — **thực thi ở E1 vẫn cần duyệt sửa workflow**
- **Bối cảnh:** Workflow intraday/daily hiện có `contents: write`, tự commit JSONL ledger vào `main`. Sync cần đọc ledger đã commit.
- **Lựa chọn cân nhắc:** (A) workflow GH Actions riêng trigger on push; (B) thêm step vào workflow cũ; (C) chạy tay/cron ngoài.
- **Quyết định:** **(B)** — append 1 step sync vào cuối cron workflow cũ (sau step commit-to-main), với **2 guardrail bắt buộc**:
  1. `continue-on-error: true` — sync fail **không** làm fail pipeline, **không** chặn git push (bảo vệ pipeline tiền thật đang chạy).
  2. Đặt SAU commit-to-main để đọc ledger đã persist.
- **Lý do:** Gộp 1 pipeline, data lên bảng ngay sau mỗi run, không cần cơ chế trigger riêng. User (owner) là người duyệt.
- **Hệ quả (never-do #6):** Sửa `.github/workflows/*.yml` là chạm production → E1 phải **hỏi duyệt lại + giao full-file workflow**, review kỹ concurrency, không tự ý sửa. Rủi ro chính: làm gãy cron → guardrail non-blocking là bắt buộc, không thương lượng.

---

## ADR-009 — Config surface = weights + gates + thresholds + extras (đầy đủ)
- **Trạng thái:** ACCEPTED (2026-09-12, grill vòng 2)
- **Bối cảnh:** App cho phép chỉnh cấu hình scorer. Bảng `v4_scoring_configs` đã có `factor_weights, gate_matrix, thresholds, extras_cfg`.
- **Lựa chọn cân nhắc:** (A) đầy đủ weights+gates+thresholds+extras; (B) chỉ factor weights; (C) chốt sau ở E4.
- **Quyết định:** **(A)** — bề mặt đầy đủ, khớp schema `v4_scoring_configs`.
- **Lý do:** Mục tiêu là tinh chỉnh scorer thật (không chỉ trọng số). Gate matrix (factor × regime) là đòn bẩy lớn với regime VN.
- **Hệ quả:** `config/scoring/schema.json` (E4) phải định nghĩa đủ 4 nhóm. `simulate.ts` phức tạp hơn (ước lượng ảnh hưởng gate). E5 loader `active.json` phải đọc đủ weights/gates/thresholds/extras, fail-soft từng nhóm. **One-change-per-cycle vẫn áp**: dù editor mở đủ, mỗi promote chỉ nên đổi 1 nhóm logic → UI cảnh báo.

---

## ADR-010 — Chart giá (E7) tái tạo từ ledger, KHÔNG fetch ngoài
- **Trạng thái:** ACCEPTED (2026-09-15, grill vòng 3)
- **Bối cảnh:** User muốn xem 1 mã BUY diễn biến giá sau các lần intraday + các ngày, dạng "chart OHLC", đánh dấu entry + highlight chạm TP. Nhưng **OHLC nến thật KHÔNG có trong Supabase** (ledger chỉ lưu `price` spot mỗi snap + forward returns). User chốt: "mục đích không phải xem OHLC realtime → chọn cách tối ưu nhất".
- **Lựa chọn cân nhắc:** (A) tái tạo nến từ giá snap đã có trong `v4_signals`; (B) thêm pipeline Python export OHLC thật → bảng `v4_ohlc` mới; (C) app tự fetch vnstock khi xem.
- **Quyết định:** **(A)**. Mỗi mã vn100 chấm mỗi ngày → có chuỗi giá snap. Dựng nến daily (O=snap đầu, C=snap cuối, H=max, L=min) + đường intraday ngày 0. Nhãn rõ "không phải tick OHLC đầy đủ".
- **Lý do:** Giữ kiến trúc **app = lớp query** (PRD non-goal: app không tự fetch chứng khoán). Không thêm bảng/pipeline/secret. Data đã sync + anon đọc được. Đủ cho mục đích theo dõi diễn biến + hit TP (đối chiếu `mfe_pct`).
- **Hệ quả:** Nến thô (≤5 điểm/ngày) — chấp nhận, dán nhãn. TP-hit suy từ giá snap ≥ tp (đối chiếu mfe_pct khi outcome chín).
- **Cập nhật 2026-09-15 — ĐÃ bổ sung phương án B** (user muốn nến daily thật + backfill quá khứ): thêm bảng `v4_ohlc` (migration 0005) + `scripts/export_ohlc_to_supabase.py` (vnstock VCI, chạy qua workflow `backfill_ohlc.yml`). Chart `/buy` **đọc `v4_ohlc` trước** (nến daily thật, lịch sử ~400 ngày); **fallback về nến-từ-snap (A)** khi mã chưa có OHLC. A vẫn giữ cho marker BUY/intraday strip (từ snap). Cần secret VNSTOCK_API_KEY (đã có) + chạy workflow backfill.

---

## ADR-012 — E8: theo dõi TP/SL & tương quan biến (trang /phan-tich)
- **Trạng thái:** ACCEPTED (2026-09-16)
- **Bối cảnh:** User muốn (1) xem tín hiệu BUY/SBUY theo thời gian trực quan; (2) mỗi tín hiệu chạm ĐÚNG TP của chính thời điểm đó (TP hôm qua ≠ TP hôm nay); (3) khi hit TP/SL thì biến đầu vào nào liên quan để điều chỉnh; (4) góc từng-mã + tổng thể.
- **Evidence data (đã kiểm):** outcomes chín chỉ 333 (BUY/SBUY, lens=trade, 30/07–25/08, 46 mã). TP/SL/entry RIÊNG chỉ populated từ T9/2026 → **overlap (own-TP + outcome chín) ≈ 0 hôm nay**, tự đầy từ cuối T9 (forward). Biến `s_*` có ở cả kỳ cũ → tương quan tính được ngay. `v4_ohlc` đủ để đi theo giá xác định TP/SL chạm trước.
- **Quyết định (user chốt 3 ngã rẽ):** (a) **cả hai** định nghĩa hit — TP riêng (forward, tự đầy) + mục tiêu CHUẨN ±3%/±6% (chạy ngay); (b) xác định chạm trước bằng **đi theo nến v4_ohlc** (chính xác thứ tự + ngày), quy ước bảo thủ TP&SL cùng ngày → SL trước; (c) **trang mới /phan-tich**.
- **Cài đặt:** migration 0008 — 2 view read-only: `v4_signal_results` (path-walk v4_ohlc: std +6/−4, +3/−3, own tp1/tp2/sl + days) và `v4_hit_factor_corr` (corr(biến s_*, ret_5d) & corr(biến, chạm TP) — **KHÁM PHÁ, không phải IC chính thức** theo Golden rule #3). Grant anon SELECT (chỉ aggregate data vốn public). UI `components/analysis-board.tsx`: tab Tổng thể (thanh tỷ lệ TP/SL/chưa chạm theo BUY vs SBUY + xếp hạng tương quan biến diễn giải tiếng Việt) + tab Từng mã (timeline chấm màu + bảng chi tiết).
- **Kết quả forward thật (ghi nhận, không kết luận):** std +6/−4: TP 12.9% / SL 22.5% / chưa chạm 64.6%. std +3/−3: TP 41.4% / SL 39.6%. Tương quan nổi bật: s_mkt_context −0.44, s_rs_reversal +0.21 (corr_win +0.38), s_dist_52w −0.18, total_score ≈ 0. Mẫu 1 tháng, scoring version cũ → chỉ là gợi ý soi trọng số, không nhân quả.
- **Hệ quả:** Cửa sổ hit cố định ~10 phiên (+16 ngày lịch) — nếu đổi horizon phải sửa view. Own-TP đang trống, page tự hiện khi outcome T9 chín. Không thêm pipeline/secret; app vẫn là lớp query.

---

## ADR-011 — Độ vững tín hiệu BUY (D/E/F) qua view read-only, không đụng scoring
- **Trạng thái:** ACCEPTED (2026-09-16)
- **Bối cảnh:** Review "để mua ngắn hạn" chỉ ra list BUY thiếu 3 lớp thông tin: (D) thanh khoản — mã mỏng khó vào/ra, dễ trượt giá; (E) độ bền — mã "nháy 1 lần" khác mã giữ BUY nhiều phiên; (F) đồng thuận intraday — BUY cả ngày khác BUY chớp 1 snap. (G) %vs TC đã có từ prevClose OHLC (phủ 100% mã BUY hiện tại; ref/tc trong breakdown = null nên không có nguồn fallback khác) → coi như đã đạt.
- **Lựa chọn cân nhắc:** (A) view SQL tổng hợp; (B) kéo trailing signals về client rồi tính TS; (C) thêm cột vào pipeline Python.
- **Quyết định:** **(A)** cho E/F — view `v4_buy_robustness` (migration 0007) tổng hợp `buy_days_15d/total_days_15d`, `buy_snaps_today/total_snaps_today`, `first_buy_snap_vn` cho các mã BUY của run mới nhất. **D** đọc thẳng `breakdown->>'adtv_bil'` (đã có trong `v4_signals`), không cần view.
- **Lý do:** Không reimplement scoring (chỉ COUNT/aggregate trên data đã public) → hợp Golden rule "một nguồn chân lý". View gọn hơn kéo ~3k dòng về client (B); không cần chờ pipeline (C). Grant anon SELECT như `v4_buy_expectancy` — không lộ thêm thông tin.
- **Hệ quả:** App `/buy` thêm badge ⚡ thanh khoản (đỏ <3 tỷ, vàng <10 tỷ), "bền {n}/{N} phiên", "{n}/{N} snap · từ HH:MM"; sort mới (bền / thanh khoản); toggle "ẩn mã <10 tỷ". Ngưỡng thanh khoản (3/10 tỷ) là mặc định UI, **không** phải gate scoring. View tính "latest BUY run" nội bộ (cùng logic page.tsx) — nếu đổi cách chọn run phải sync 2 nơi.

---

## ADR-006 — `run_id` deterministic (CLOSED ở E1)
- **Trạng thái:** ✅ ACCEPTED (2026-09-12, E1)
- **Bối cảnh:** `v4_runs` cần `run_id` (PK) nhưng ledger prediction không có field `run_id`.
- **Chốt:** `run_id = f"{signal_date}_{snap_time}"` (vd `2026-09-03_09:27`). `kind='intraday'`.
- **Evidence:** predictions 2026-09 — 1 "run" = đúng `(signal_date, snap_time)` → mỗi run 100 mã, `scoring_version` hằng số trong run (0 run có >1 version), flow/universe hằng. 37 run/tháng. Không cần đưa version vào run_id (đã hằng). Mọi run v4 là snap intraday → kind='intraday'; daily flow chưa xuất hiện trong ledger v4.
- **Hệ quả:** Human-readable, idempotent (cùng run → cùng id → upsert không nhân đôi). Nếu sau này có daily flow, map lại `kind` theo flow/snap.
