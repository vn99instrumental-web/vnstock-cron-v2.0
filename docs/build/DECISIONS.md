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

## ADR-002 — Schema `v4_outcomes` (wide vs long): **TREO, chốt ở E1**
- **Trạng thái:** DEFERRED → sẽ quyết trong E1 (2026-09-12)
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

## ADR-006 — `run_id` sinh deterministic ở sync (ledger không có sẵn)
- **Trạng thái:** PROPOSED (2026-09-12) — xác nhận ở E1
- **Bối cảnh:** `v4_runs` cần `run_id` (PK) nhưng ledger prediction không có field `run_id`; chỉ có `snap_time`, `signal_date`, `scoring_version`, `flow`.
- **Quyết định (đề xuất):** Sinh `run_id` deterministic từ tổ hợp `(signal_date, snap_time, scoring_version, kind)` (vd hash ngắn hoặc concat). Đảm bảo idempotent: cùng run → cùng id → upsert không nhân đôi.
- **Lý do:** Cần group signals theo run cho trang Today; idempotency.
- **Hệ quả:** E1 chốt công thức chính xác + `kind` (intraday/daily) suy từ snap_time hoặc flow. Xác nhận khi code sync.
