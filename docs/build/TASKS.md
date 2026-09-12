# TASKS — Backlog epic → task

> Backlog thực thi. Mỗi task: **ID · skill gate · Definition of Done · status · dependency**.
> Cập nhật `status` **ngay khi xong task**. Nguồn chân lý trạng thái build tổng: `PROJECT_STATE.md`.
> Status: `TODO · DOING · BLOCKED · DONE · NEEDS-APPROVAL`

**Ngày:** 2026-09-12 · **HEAD gốc:** `38de5bb`

---

## E0 — Foundation *(DOING)*

| ID | Task | Skill | Definition of Done | Status | Dep |
|---|---|---|---|---|---|
| E0.1 | Verify connections (Supabase/GitHub/n8n) | — | 3 connection sống + 5 bảng `v4_*` tồn tại RLS-on (evidence log) | **DONE** | — |
| E0.2 | Viết `PRD.md` comprehensive (E0-E6) | grill-me | PRD khớp HEAD thật, có acceptance criteria từng epic | **DONE** | E0.1 |
| E0.3 | Viết `PLAN.md` (phase + dependency + cadence) | — | Lộ trình + dependency graph + milestone | **DONE** | E0.2 |
| E0.4 | Viết `DECISIONS.md` (ADR khởi tạo) | — | ADR-001..006 (shared-project, outcomes-deferred, source-of-truth, config-driven, promote-security, run_id) | **DONE** | E0.2 |
| E0.5 | Viết `TASKS.md` (backlog) | — | Backlog E0-E6 có DoD/dep/status | **DONE** | E0.2 |
| E0.6 | Viết `PROJECT_STATE.md` | project-update | State khớp evidence repo | **DONE** | E0.2 |
| E0.7 | Commit + push branch `claude/bold-pascal-768taz` | — | Push thành công, working tree clean | **TODO** | E0.2-6 |

---

## E1 — Data Sync (JSONL → Supabase)

| ID | Task | Skill | Definition of Done | Status | Dep |
|---|---|---|---|---|---|
| E1.1 | Chốt ADR-002 schema outcomes (wide/long) | grill-me | ADR-002 CLOSED = WIDE | **DONE** | E0 |
| E1.2 | Migration `0002` đổi `v4_outcomes` sang WIDE | — | Applied (Supabase), 21 cột khớp ledger, unique(symbol,signal_date,snap_time,lens) | **DONE** | E1.1 |
| E1.3 | Chốt ADR-006 công thức `run_id` | — | `run_id=signal_date_snap_time`, kind='intraday' | **DONE** | E0 |
| E1.4 | Viết `scripts/sync_supabase.py` (predictions → v4_signals + v4_runs) | — | py_compile OK; transform 3700→3700 signals+37 runs; breakdown=full record; version khớp | **DONE** | E1.3 |
| E1.5 | Sync outcomes → v4_outcomes | — | build_outcome_row 1-1 khớp schema wide | **DONE** | E1.2 |
| E1.6 | Test idempotency + schema (DB thật) | app-test | Upsert 2× qua MCP → counts 1/2/1 không đổi; FK+unique OK; dọn về 0 rows | **DONE** | E1.4-5 |
| E1.7 | Security review (service_role, không log secret) | security-review | **DONE** — PASS, 0 Critical/High/Med; fix gitignore __pycache__; note escape breakdown ở E3 | **DONE** | E1.4-5 |
| E1.8 | **HỎI DUYỆT** + append step sync non-blocking vào cron workflow cũ (ADR-008) | grill-me, security-review | User approve; step SAU commit-to-main, `continue-on-error: true`; sync fail → pipeline vẫn xanh + git push vẫn chạy; giao full-file workflow | NEEDS-APPROVAL | E1.6-7 |
| E1.9 | Sync FULL data thật lên bảng (chạy script server-side có service key) | — | Row count Supabase khớp ledger; cần env SUPABASE_SERVICE_ROLE_KEY (chỉ có ở server/GH Actions) | BLOCKED (thiếu key ở phiên local) | E1.7-8 |

---

## E2 — Web Foundation

| ID | Task | Skill | Definition of Done | Status | Dep |
|---|---|---|---|---|---|
| E2.1 | Design khung app + nav (5 route) | frontend-design | Mockup/spec route today/history/history/[id]/config/ic | TODO | E0 |
| E2.2 | Scaffold `web/` Next.js App Router + TS | — | dev/build chạy; route trống render | TODO | E2.1 |
| E2.3 | `lib/supabase/{server,client}.ts` (đúng lớp key) | — | Server dùng service (chỉ server), client dùng anon | TODO | E2.2 |
| E2.4 | Supabase Auth **đơn owner** (login) + `middleware.ts` (ADR-007) | — | Chặn /config + Promote khi chưa auth; allowlist 1 email owner; public route mở | TODO | E2.3 |
| E2.5 | Verify secret không vào client bundle | security-review | grep bundle sạch; review pass | TODO | E2.3-4 |
| E2.6 | Visual QA khung + responsive | visual-qa | Desktop + mobile OK | TODO | E2.2 |

---

## E3 — Read Dashboards

| ID | Task | Skill | Definition of Done | Status | Dep |
|---|---|---|---|---|---|
| E3.1 | Design Today/History/Drill-down | frontend-design | Spec bảng, filter, badge version động | TODO | E2 |
| E3.2 | Trang `today` (run mới nhất) | — | Khớp `v4_runs.started_at` max; version động | TODO | E1, E3.1 |
| E3.3 | Trang `history` (filter + phân trang server-side) | — | Filter ngày/mã/decision; empty/loading/error states | TODO | E1, E3.1 |
| E3.4 | Trang `history/[id]` (drill-down) | — | Breakdown `s_*`/gates/ranks/shadow/outcome. **Escape khi render `breakdown` jsonb** (XSS defense-in-depth — note từ security-review E1) | TODO | E1, E3.1 |
| E3.5 | App-test luồng đọc | app-test | Routing/filter/drill-down pass | TODO | E3.2-4 |
| E3.6 | Visual QA | visual-qa | Responsive + states OK | TODO | E3.2-4 |

---

## E4 — Config & Promote

| ID | Task | Skill | Definition of Done | Status | Dep |
|---|---|---|---|---|---|
| E4.1 | Grill-me + design Config editor | grill-me, frontend-design | Chốt UX editor + schema.json shape | TODO | E3 |
| E4.2 | `config/scoring/schema.json` (validate) | — | Schema đủ 4 nhóm: factor_weights + gate_matrix + thresholds + extras_cfg (ADR-009) | TODO | E4.1 |
| E4.3 | Trang `config` editor + validate | — | Config sai schema bị chặn | TODO | E4.2 |
| E4.4 | `lib/scoring/simulate.ts` (nhãn simulation) | — | Output dán nhãn "simulation"; không dùng làm căn cứ chính thức | TODO | E4.3 |
| E4.5 | `app/api/promote/route.ts` (server-only) | security-review | Ghi active.json qua GITHUB_TOKEN + row config production; authenticated-only | TODO | E4.3 |
| E4.6 | Enforce one-change-per-cycle + shadow≥30 | — | UI cảnh báo >1 thay đổi; chặn promote khi chưa đủ shadow | TODO | E4.5 |
| E4.7 | Security review (Promote/secret/input) | security-review | Pass; secret không ra client | TODO | E4.5 |
| E4.8 | App-test + Visual QA | app-test, visual-qa | Luồng promote + hiển thị OK | TODO | E4.5 |

---

## E5 — Scorer config-driven *(NEEDS-APPROVAL · Python)*

| ID | Task | Skill | Definition of Done | Status | Dep |
|---|---|---|---|---|---|
| E5.0 | **HỎI DUYỆT** sửa `steps/v2f_step_scoring_v4.py` | grill-me | User approve rõ ràng | **NEEDS-APPROVAL** | E4 |
| E5.1 | Loader đọc `active.json` + fallback registry | — | `py_compile`+AST pass; không config → output byte-identical | TODO | E5.0 |
| E5.2 | Shadow fields + bump version khi đổi số | — | Shadow ghi riêng; đổi số → bump SCORING_VERSION + reset bucket | TODO | E5.1 |
| E5.3 | Security review (production Python) | security-review | Pass | TODO | E5.1 |
| E5.4 | Shadow ≥30 phiên trước promote thật | — | Đủ 30 phiên forward → mới promote | TODO | E5.2 |

---

## E6 — IC Evaluator

| ID | Task | Skill | Definition of Done | Status | Dep |
|---|---|---|---|---|---|
| E6.1 | `scripts/export_ic_to_supabase.py` (rank-IC Python) | — | Spearman per (config_version, factor, horizon); join s_* × ret_h | TODO | E1 |
| E6.2 | Ghi `v4_ic_metrics` idempotent | — | Unique config_version+factor+horizon; re-run không nhân đôi | TODO | E6.1 |
| E6.3 | Trang `ic` (bảng/heatmap) | frontend-design | Hiển thị IC; empty state khi thiếu mẫu | TODO | E2, E6.2 |
| E6.4 | App-test + Visual QA | app-test, visual-qa | Luồng + hiển thị OK | TODO | E6.3 |

---

## Cột mốc cập nhật
- 2026-09-12: Khởi tạo backlog. E0.1-E0.7 DONE (push `adb5d4f`).
- 2026-09-12 (grill vòng 2): chốt ADR-007 (auth 1 owner), ADR-008 (sync non-blocking vào workflow cũ), ADR-009 (config surface đầy đủ); sửa decision buckets đúng data. Thêm E1.8. PRD → v2.0 GRILLED.
