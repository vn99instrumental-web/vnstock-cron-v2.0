# PRD — VNStock Signals App (v2.0)

> Yêu cầu sản phẩm & acceptance criteria. **Không code trái PRD**; nếu cần lệch → ghi ADR trong `DECISIONS.md` trước.
> Bản này là **comprehensive**, phủ E0→E6. Đọc kèm `CLAUDE.md` (hiến pháp) và `PLAN.md` (lộ trình).

**Version:** 1.0 · **Ngày:** 2026-09-12 · **HEAD gốc:** `38de5bb` · **Trạng thái:** DRAFT (chờ duyệt)

---

## 0. TL;DR (1 phút)

App web **hiển thị + điều chỉnh** cho pipeline chấm điểm cổ phiếu VN. App **không** thay bộ não Python. App là:
- **Lớp truy vấn**: mirror ledger JSONL → Supabase → UI đọc.
- **Lớp tương tác**: xem tín hiệu (Today/History), soi chất lượng nhân tố (IC), và **đề xuất → shadow → promote** cấu hình chấm điểm (weights/gates/thresholds) mà không sửa tay file Python.

**Nguồn chân lý con số:** Python pipeline (GitHub Actions, n8n trigger 5×/ngày). App **chỉ mirror + đề xuất**, không tự chấm điểm chính thức.

---

## 1. Mục tiêu & phi mục tiêu

### 1.1 Mục tiêu (Goals)
| # | Mục tiêu | Đo lường thành công |
|---|---|---|
| G1 | Xem tín hiệu mua/bán mới nhất tức thì | Trang Today load < 2s, hiển thị đúng `n_buy`/decision của run gần nhất |
| G2 | Truy vết lịch sử 1 mã / 1 phiên | History filter theo ngày/mã/decision; drill-down 1 tín hiệu ra full breakdown |
| G3 | Đo chất lượng nhân tố (forward IC) | Trang IC hiển thị rank-IC theo factor × horizon, cập nhật sau mỗi lần evaluator chạy |
| G4 | Điều chỉnh scorer an toàn (shadow-first) | Đề xuất config → shadow ≥30 phiên → promote 1-click ghi `active.json` qua server |
| G5 | Version-agnostic | UI đọc `scoring_version`/`gate_version` động từ data, không hardcode |

### 1.2 Phi mục tiêu (Non-goals) — chốt để chống scope creep
- ❌ **Không** reimplement công thức chấm điểm/IC bằng TS làm căn cứ chính thức. `simulate.ts` chỉ ước lượng, dán nhãn "simulation".
- ❌ **Không** đặt lệnh, kết nối broker, hay khuyến nghị đầu tư (đây là công cụ nghiên cứu tín hiệu).
- ❌ **Không** sửa logic pipeline ngoài đúng 1 điểm mở rộng (E5: đọc `active.json`) và điểm đó **shadow-first + cần duyệt**.
- ❌ **Không** realtime intraday streaming trong app (app đọc snapshot đã sync, không tự fetch chứng khoán).
- ❌ **Không** quản lý người dùng phức tạp/RBAC nhiều vai; chỉ 1 lớp gate: public read vs authenticated config.
- ❌ **Không** backtest engine mới trong app; what-if chỉ là simulation tách bạch, forward outcomes mới quyết.

---

## 2. Người dùng & bối cảnh sử dụng

| Persona | Nhu cầu | Quyền |
|---|---|---|
| **Chủ hệ thống (anh)** | Xem tín hiệu, soi IC, tinh chỉnh config, promote | Authenticated: full read + Promote |
| **Người xem ẩn danh** | Xem tín hiệu công khai (repo vốn public) | Anon: read signals/outcomes/ic, **không** thấy config editor/Promote |

Bối cảnh: desktop-first (bàn làm việc, soi bảng số), nhưng **phải dùng được trên mobile** (xem nhanh Today khi ngoài đường).

---

## 3. Nguồn dữ liệu & luồng (data flow)

```
Python pipeline (GH Actions, n8n 5×/ngày)
   └─ ghi JSONL ledger (append-only, nguồn chân lý)
        output/history/v2f_predictions_v4/*.jsonl   (tín hiệu)
        output/history/v2f_outcomes_v4/*.jsonl      (forward returns)
   └─ [E5] đọc config/scoring/active.json (weights/gates/thresholds) + fallback registry
        │
        ▼
[E1] scripts/sync_supabase.py  (service_role, server-side)
        │ upsert
        ▼
Supabase Postgres 17  (mirror)  v4_runs · v4_signals · v4_outcomes · v4_ic_metrics · v4_scoring_configs
        │ RLS: anon/auth read; ghi chỉ service_role
        ▼
[E2-E4] Next.js app (Vercel)  ── đọc anon key ──▶ Today/History/IC (public)
        │                                        └▶ Config/Promote (authenticated)
        └─ [E4] api/promote  ── service key + GITHUB_TOKEN ──▶ commit active.json vào repo
[E6] scripts/export_ic_to_supabase.py  ── tính rank-IC ──▶ v4_ic_metrics
```

**Bất biến dữ liệu:**
- Ledger JSONL = append-only, **không sửa quá khứ**. Sync là idempotent upsert (unique keys).
- Con số điểm/IC "chính thức" **chỉ** từ Python. Supabase là bản sao, không phải nơi tính.

---

## 4. Mô hình dữ liệu (đã có migration 0001, đối chiếu ledger thật)

Bảng `v4_*` đã tạo trên Supabase (migration `20260912085136_vnstock_app_v4_init`), RLS on. Đối chiếu với ledger thật:

| Bảng | Nguồn | Ghi chú lệch cần xử lý |
|---|---|---|
| `v4_runs` | derive từ predictions (group theo run) | Chưa có `run_id` trong ledger → E1 phải sinh (vd hash snap_time+scoring_version) |
| `v4_signals` | `v2f_predictions_v4/*.jsonl` | Ledger dùng `decision ∈ {NEUTRAL, SELL, BUY, ...}`; nhiều field shadow (`score_trade_nomr`, `decision_altfund`...) + factor scores `s_*` → gói vào `breakdown` jsonb |
| `v4_outcomes` | `v2f_outcomes_v4/*.jsonl` | **⚠️ LỆCH SCHEMA**: ledger **wide** (`ret_1d/3d/5d/10d`, `mfe_pct`, `mae_pct`, `lens`); migration đang **long** (`horizon`, `ret`). **Chốt ở E1 (ADR-002).** |
| `v4_scoring_configs` | app ghi (Config/Promote) | lifecycle: `draft → shadow → production → archived` |
| `v4_ic_metrics` | `export_ic_to_supabase.py` | rank-IC per (config_version, factor, horizon) |

Chi tiết field ledger thật (evidence, đọc `2026-09.jsonl`):
- **prediction**: `pred_id, symbol, signal_date, snap_time, scoring_version(str "v4.17"), registry_version(int), gate_version(int), decision, confidence, total_score, score_trade, score_hold, regime, gates{6 factor→multiplier}, price, industry, ranks(rank_*), ff_intra_*, of_bp_pts, entry/stop/tp1/tp2(nullable), result_5d/30d(PENDING), factor scores s_*(int), shadow: score_trade_altfund/nomr/rank/gate1 + decision_*`.
- **outcome**: `pred_id, symbol, signal_date, snap_time, eval_date, lens('trade'), scoring_version, scoring_version_effective, decision, total_score, t0_close, n_bars, ret_1d/3d/5d/10d, mfe_pct, mae_pct`.

---

## 5. Epic breakdown & acceptance criteria (E0→E6)

> Mỗi epic: mục tiêu · phạm vi · Definition of Done (DoD) đo được · skill gate. Backlog task chi tiết trong `TASKS.md`.

### E0 — Foundation *(epic hiện tại)*
- **Mục tiêu:** dựng nền tài liệu build + xác nhận connection/env, chưa đụng code.
- **Phạm vi:** `docs/build/{PRD,PLAN,TASKS,DECISIONS}.md`, `PROJECT_STATE.md`.
- **DoD:**
  - [x] Connection verified: Supabase `ACTIVE_HEALTHY`, GitHub auth `vn99instrumental-web`, n8n workflow active, 5 bảng `v4_*` tồn tại RLS-on.
  - [ ] 5 file docs tồn tại, nội dung khớp HEAD thật (không suy diễn).
  - [ ] ADR khởi tạo: shared-project, outcomes-schema-deferred, source-of-truth.
- **Skill gate:** `grill-me` (mở màn) → `project-update` (chốt state).

### E1 — Data Sync (JSONL → Supabase)
- **Mục tiêu:** mirror ledger vào Supabase idempotent.
- **Phạm vi:** `scripts/sync_supabase.py` (server-side, service_role). Đọc predictions_v4 + outcomes_v4, upsert `v4_runs/v4_signals/v4_outcomes`.
- **Quyết định treo cần chốt:** ADR-002 schema outcomes (wide vs long). Nếu wide → migration `0002` đổi bảng.
- **DoD:**
  - [ ] Chạy sync tháng 2026-09 → row count Supabase khớp số dòng ledger (trừ duplicate theo unique key).
  - [ ] Re-run 2 lần → không nhân đôi row (idempotent, verify bằng `count(*)`).
  - [ ] `scoring_version/gate_version` trong `v4_signals` khớp ledger từng dòng (spot-check 5 mã).
  - [ ] Secret `SUPABASE_SERVICE_ROLE_KEY` chỉ ở env server, không log ra.
- **Skill gate:** `security-review` (chạm Supabase/secret) → `app-test`.

### E2 — Web Foundation
- **Mục tiêu:** khung Next.js chạy được + auth + kết nối Supabase đúng lớp (server/client key).
- **Phạm vi:** `web/` (App Router, TS), `lib/supabase/{server,client}.ts`, `middleware.ts`, Supabase Auth (login), layout + nav dashboard.
- **DoD:**
  - [ ] `web/` build & dev chạy; trang trống các route `(dashboard)/{today,history,history/[id],config,ic}` render.
  - [ ] Anon key ở client, service key **không** vào client bundle (verify: grep bundle/`security-review`).
  - [ ] Middleware chặn `/config` + Promote khi chưa auth; public route mở.
- **Skill gate:** `frontend-design` (trước code) → `security-review` → `app-test` → `visual-qa`.

### E3 — Read Dashboards (Today / History)
- **Mục tiêu:** đọc & hiển thị tín hiệu từ Supabase.
- **Phạm vi:** `today` (run gần nhất: danh sách decision, score, regime, badge version), `history` (filter ngày/mã/decision, phân trang), `history/[id]` (drill-down full breakdown jsonb + shadow fields + trade levels + outcome nếu có).
- **DoD:**
  - [ ] Today hiển thị đúng run mới nhất (khớp `v4_runs.started_at` max).
  - [ ] Version badge đọc **động** từ row (không hardcode "v4.17").
  - [ ] History filter + phân trang hoạt động; empty/loading/error states có.
  - [ ] Drill-down 1 tín hiệu: breakdown factor `s_*`, gates, ranks, shadow decisions, outcome ret_* (nếu matured).
- **Skill gate:** `frontend-design` → `app-test` → `visual-qa`.

### E4 — Config & Promote
- **Mục tiêu:** đề xuất config chấm điểm + promote an toàn (shadow-first).
- **Phạm vi:** `config` (editor weights/gates/thresholds, đọc schema từ `config/scoring/schema.json`), `lib/scoring/simulate.ts` (ước lượng, **nhãn simulation**), `app/api/promote/route.ts` (server-only: validate schema → commit `active.json` vào repo qua `GITHUB_TOKEN`), lifecycle `v4_scoring_configs`.
- **DoD:**
  - [ ] Editor validate theo `schema.json`; config sai schema bị chặn.
  - [ ] Simulate luôn hiển thị nhãn "simulation — không phải điểm chính thức".
  - [ ] Promote: chỉ authenticated; ghi `active.json` + tạo row config `status=production`, `promoted_at` set; audit log.
  - [ ] `GITHUB_TOKEN`/`service_role` **không** ra client (security-review pass).
  - [ ] Enforce **one-change-per-cycle**: UI cảnh báo nếu đổi >1 nhóm; shadow ≥30 phiên trước promote.
- **Skill gate:** `grill-me` (epic mở) → `frontend-design` → `security-review` (bắt buộc, chạm Promote/secret) → `app-test` → `visual-qa`.

### E5 — Scorer config-driven *(Python · CẦN DUYỆT)*
- **Mục tiêu:** `steps/v2f_step_scoring_v4.py` đọc weights/gates/thresholds từ `config/scoring/active.json`, fallback registry khi thiếu.
- **Evidence hiện trạng:** hiện hardcode `SCORING_VERSION="v4.17"` + import từ `utils.v2f_registry`; **chưa** đọc config ngoài.
- **Phạm vi:** thêm loader `active.json` (fail-soft → registry defaults), giữ nguyên math; bump `SCORING_VERSION` khi đổi số → reset forward bucket.
- **DoD:**
  - [ ] `py_compile` + AST validate pass.
  - [ ] Không có `active.json` → hành vi y hệt hiện tại (fallback registry, byte-identical output trên 1 phiên mẫu).
  - [ ] Có `active.json` shadow → ghi field shadow, **không** đổi production score cho tới khi promote.
  - [ ] Shadow ≥30 phiên trước promote; đổi số → bump version + reset bucket.
- **Skill gate:** **HỎI DUYỆT TRƯỚC** → `grill-me` → `security-review` → giao full-file.

### E6 — IC Evaluator
- **Mục tiêu:** đo forward rank-IC per factor × horizon.
- **Evidence:** evaluator hiện chỉ tính `ret_Nd` (forward returns), **chưa** tính IC → E6 greenfield, không sửa file eval cũ.
- **Phạm vi:** `scripts/export_ic_to_supabase.py` — join predictions factor scores `s_*` với outcomes `ret_h`; tính Spearman rank-IC; ghi `v4_ic_metrics`. Trang `ic` hiển thị.
- **DoD:**
  - [ ] IC tính bằng Python (không phải TS chính thức); Spearman theo (config_version, factor, horizon).
  - [ ] Ghi `v4_ic_metrics` idempotent (unique config_version+factor+horizon).
  - [ ] Trang IC: bảng/heatmap IC, cập nhật sau evaluator; empty state khi chưa đủ mẫu.
- **Skill gate:** `security-review` → `app-test` → `visual-qa`.

---

## 6. Yêu cầu phi chức năng (NFR)

| Nhóm | Yêu cầu |
|---|---|
| **Bảo mật** | `service_role`/`GITHUB_TOKEN` chỉ server. Anon key ra client. RLS: read public cho signals/outcomes/ic; config read = authenticated; mọi write qua service_role. Promote server-only, validate schema, không nhận input tuỳ tiện. |
| **Version-agnostic** | Không hardcode version/weight/gate trong `web/`. Đọc động từ data/output. |
| **Idempotency** | Sync + IC export re-run không nhân đôi row (unique keys). |
| **Performance** | Today < 2s; History phân trang server-side (không kéo cả bảng). Index đã có theo date/symbol/decision. |
| **Responsive/A11y** | Desktop-first, mobile dùng được. Nhãn UI tiếng Việt; giữ tên chỉ báo (RSI, MFI...). Contrast đạt, keyboard-nav cơ bản. |
| **Observability** | `v4_runs.health` jsonb ghi trạng thái sync; app hiển thị "cập nhật lúc". |
| **Không phá app khác** | Project Supabase dùng chung nhiều app (vibe_space, poems, qcvn...). Chỉ đụng bảng `v4_*`. Không bật RLS bảng app khác (khoá app cũ user). |

---

## 7. Rủi ro & giả định

| # | Rủi ro/giả định | Ảnh hưởng | Xử lý |
|---|---|---|---|
| R1 | Lệch schema outcomes wide/long | Sync sai/khó query | ADR-002, chốt ở E1 trước khi code sync |
| R2 | `run_id` không có sẵn trong ledger | Không group được run | E1 sinh deterministic run_id từ (snap_time, scoring_version, kind) |
| R3 | Sửa scoring_v4 làm lệch production | Mất tin cậy con số | E5 shadow-first ≥30 phiên, fail-soft fallback, cần duyệt |
| R4 | Secret rò ra client bundle | Lộ service_role/PAT | security-review bắt buộc E2/E4; grep bundle |
| R5 | RLS thiếu policy khoá app khác | Hỏng app cũ user | Chỉ chạm bảng `v4_*`; không sửa bảng khác |
| R6 | Project Supabase free tier pause | App/sync gãy | Theo dõi status; ngoài scope app |

---

## 8. Acceptance criteria tổng (Definition of Done cho v2.0)

- [ ] Today/History/IC đọc data thật từ Supabase, version hiển thị động.
- [ ] Config→shadow→promote chạy đúng, ghi `active.json` qua server, không rò secret.
- [ ] scoring_v4 đọc `active.json` fallback-safe (E5, sau duyệt + shadow).
- [ ] IC evaluator ghi `v4_ic_metrics`, trang IC hiển thị.
- [ ] Toàn bộ gate skill pass trước mỗi merge (security-review + app-test + visual-qa cho UI/nhạy cảm).
- [ ] `PROJECT_STATE.md` phản ánh đúng trạng thái sau mỗi merge.

---

## 9. Tham chiếu
- Hiến pháp: `CLAUDE.md` (golden rules, never-do, skill workflow).
- Lộ trình: `docs/build/PLAN.md`. Backlog: `docs/build/TASKS.md`. Quyết định: `docs/build/DECISIONS.md`.
- Migration hiện tại: `supabase/migrations/0001_init.sql` (đã apply).
