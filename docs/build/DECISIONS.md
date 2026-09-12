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

## ADR-006 — `run_id` sinh deterministic ở sync (ledger không có sẵn)
- **Trạng thái:** PROPOSED (2026-09-12) — xác nhận ở E1
- **Bối cảnh:** `v4_runs` cần `run_id` (PK) nhưng ledger prediction không có field `run_id`; chỉ có `snap_time`, `signal_date`, `scoring_version`, `flow`.
- **Quyết định (đề xuất):** Sinh `run_id` deterministic từ tổ hợp `(signal_date, snap_time, scoring_version, kind)` (vd hash ngắn hoặc concat). Đảm bảo idempotent: cùng run → cùng id → upsert không nhân đôi.
- **Lý do:** Cần group signals theo run cho trang Today; idempotency.
- **Hệ quả:** E1 chốt công thức chính xác + `kind` (intraday/daily) suy từ snap_time hoặc flow. Xác nhận khi code sync.
