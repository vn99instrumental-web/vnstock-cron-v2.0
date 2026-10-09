# PROJECT_STATE.md — Trạng thái build (nguồn chân lý)

> Tái sinh từ **chứng cứ repo thật** (không suy diễn). Đọc đầu mỗi phiên.
> Do skill `project-update` cập nhật sau mỗi merge.

**Cập nhật:** 2026-10-09 · **Branch:** `main` · **PRD:** v2.0 GRILLED

---

## 1. Ta đang ở đâu

**Ứng dụng đã vận hành production.** Repo hiện có pipeline Python, đồng bộ Supabase, dashboard Next.js trong `web/`, cấu hình scoring và các workflow cron; các mục chi tiết bên dưới ghi lại những mốc đã xác minh.

---

## 2. Đã có gì (evidence-verified)

### Pipeline Python (production, KHÔNG đụng khi chưa duyệt)
- `steps/` — 20 file. Scorer production: `v2f_step_scoring_v4.py` (`SCORING_VERSION="v4.17"`, `GATE_VERSION=7`, `REGISTRY_VERSION=3`, import weights/gates từ `utils/v2f_registry.py`). **Hardcode, chưa đọc config ngoài.**
- `utils/` — 21 file (registry, indicators_meta, regime_v42, sector_map...).
- `scripts/` — ~40 file diag/eval. Evaluator forward: `v2f_step_eval_predictions.py` (tính `ret_1d/3d/5d/10d`, **chưa** tính IC).
- `.github/workflows/` — 8 workflow (cron_daily, cron_intraday, cron_news, cron_weekly, v2f_data_qc, backtest, pages, debug).
- Ledger JSONL `output/history/`:
  - `v2f_predictions_v4/`: 2026-07/08/09 (tháng 09 = 8MB, có data mới).
  - `v2f_outcomes_v4/`: 2026-07/08 (09 chưa mature).

### Supabase (project `mcaqnaomzoqgxccdgvls`, Postgres 17.6, ACTIVE_HEALTHY)
- Migration `0001_init.sql` **đã apply** (version `20260912085136_vnstock_app_v4_init`).
- 5 bảng `v4_*` tồn tại, **RLS on**, **0 rows** (chưa sync):
  `v4_runs · v4_signals · v4_outcomes · v4_scoring_configs · v4_ic_metrics`.
- Project **dùng chung** nhiều app khác (vibe_space chat/poems, qcvn, n8n_chat, staging). ⚠️ Advisory critical: 4 bảng app KHÁC tắt RLS — **không** thuộc app này, không tự sửa (ADR-001).

### Docs build (E0 — vừa tạo)
- `docs/build/PRD.md` — comprehensive E0-E6.
- `docs/build/PLAN.md` — phase + dependency + cadence.
- `docs/build/DECISIONS.md` — ADR-001..006.
- `docs/build/TASKS.md` — backlog.
- `PROJECT_STATE.md` — file này.

---

## 3. Connection check (2026-09-12)

| Connection | Trạng thái | Bằng chứng |
|---|---|---|
| Supabase | ✅ | `mcaqnaomzoqgxccdgvls` ACTIVE_HEALTHY, PG 17.6 |
| GitHub | ✅ | auth `vn99instrumental-web`, repo khớp remote |
| n8n | ✅ | workflow `Github: Push-to-Chart_100-Points-System_v2f` active |
| DB migration | ✅ | 5 bảng `v4_*` tồn tại, RLS on, 0 rows |

---

## 4. Quyết định đã chốt (grill vòng 2, 2026-09-12)

| ADR | Nội dung | Trạng thái |
|---|---|---|
| ADR-007 | Auth = Supabase Auth **đơn owner**; public read | ACCEPTED |
| ADR-008 | Sync = append step **non-blocking** vào cron workflow cũ (đặt sau commit-to-main, `continue-on-error`) | ACCEPTED — thực thi E1 cần duyệt sửa workflow |
| ADR-009 | Config surface = weights + gates + thresholds + extras (đầy đủ) | ACCEPTED |

**Fact sửa (data thật):** decision buckets = `NEUTRAL/BUY/STRONG BUY/SELL/STRONG SELL` (KHÔNG có HOLD; migration comment cũ ghi sai). "Run" = `(signal_date, snap_time)`, ~20 snap/tháng.

## 4b. Quyết định treo (cần chốt tiếp)

| ADR | Nội dung | Chốt ở |
|---|---|---|
| ADR-004 | Scorer đọc `active.json` (fallback registry) | E5 — **cần duyệt** |

## 4c. E1 — Data Sync (đang làm, 2026-09-12)

- ✅ ADR-002 CLOSED = WIDE. **Migration `0002_outcomes_wide.sql` đã apply** lên Supabase (v4_outcomes 21 cột, `unique(symbol,signal_date,snap_time,lens)`, RLS on).
- ✅ ADR-006 CLOSED: `run_id = signal_date_snap_time`, `kind='intraday'`.
- ✅ `scripts/sync_supabase.py` (full-file): stdlib+requests, zero heavy dep. Transform verified: 3700 predictions → 3700 signals + 37 runs (2026-09); outcomes 1-1 wide. py_compile OK. `breakdown` jsonb = full record (lossless drill-down). Secret chỉ đọc từ env, không log.
- ✅ Idempotency + schema verified ở DB thật (MCP): upsert 2× → counts 1/2/1 không đổi; FK v4_signals→v4_runs + unique constraint hoạt động. Đã dọn test rows về 0.
- ✅ `security-review` (E1.7) PASS.
- ✅ E1.8 (giao full-file): `v2f_cron_intraday.yml` thêm step "Sync ledger → Supabase" — SAU "Commit V2F output", `continue-on-error: true`, skip mềm khi thiếu secret. YAML hợp lệ.
- ⏳ **CHỜ ANH (2 việc thủ công) để data tự chảy lên bảng**:
  1. Set secret GitHub Actions `SUPABASE_SERVICE_ROLE_KEY` (repo Settings → Secrets → Actions). SUPABASE_URL đã hardcode (công khai).
  2. Merge branch `claude/bold-pascal-768taz` → `main`.
  → Sau đó run intraday kế tiếp (n8n 5×/ngày) sẽ tự sync (E1.9).

---

## 4d. E2 — Web Foundation (DONE code, 2026-09-12)

- ✅ `web/` scaffold: Next.js 15 (App Router) + React 19 + TS + Tailwind v4 + @supabase/ssr + Recharts.
- ✅ Shell: `(dashboard)/layout` sidebar/top-nav + header **version badge đọc động** từ v4_runs; màu semantic decision.
- ✅ 5 route placeholder (today/history/history/[id]/ic/config) + `/login` (email+password owner) + `/auth/callback`.
- ✅ `lib/supabase/{client,server,middleware}`: anon+cookie; `getUser`/`isOwner`; **service_role KHÔNG dùng ở E2**.
- ✅ Auth gate (ADR-007): `middleware.ts` chặn /config → /login; kiểm lại server-side; allowlist `NEXT_PUBLIC_OWNER_EMAIL`.
- ✅ security-review E2.5: grep web/ sạch, không rò secret ra client.
- ⏳ **Chưa verify build**: không chạy `npm install`/`next build` ở phiên (tránh cạn disk container). Anh chạy `cd web && npm install && npm run dev` (hoặc deploy Vercel) để verify + visual-qa (E2.6).

## 4e. E4 + E6 (làm song song, DONE code — 2026-09-12)

**E4 — Config & Promote:**
- ✅ `config/scoring/schema.json` (JSON Schema 4 nhóm) + `config/scoring/active.json` (baseline v4.17 mirror registry).
- ✅ `web/lib/scoring/simulate.ts` (ước lượng, nhãn SIMULATION) + `default-config.ts`.
- ✅ `web/app/api/promote/route.ts` server-only: owner gate + same-origin(CSRF) + validate + one-change guard(force) + commit active.json(GITHUB_TOKEN) + ghi v4_scoring_configs(service_role, archive→insert).
- ✅ `web/components/config-editor.tsx` + `config/page.tsx`: editor weights/gate(6×6)/thresholds/extras + panel mô phỏng + Promote.
- ✅ security-review: 0 Critical/High; low (commit+insert không atomic → 207 handled).
- ⏳ Cần env runtime `GITHUB_TOKEN` + `SUPABASE_SERVICE_ROLE_KEY` (Vercel) để promote chạy thật; app-test/visual-qa cần app chạy.

**E6 — IC Evaluator:**
- ✅ `scripts/export_ic_to_supabase.py`: TÁI SỬ DỤNG methodology IC chính thức (import `eval_forward_ic._spearman/daily_last` + `sync_supabase.Supabase`). Dry-run 64 dòng trên data 07/08 — MR IC dương mạnh nhất (+0.16@5d), khớp registry.
- ✅ Ghi `v4_ic_metrics` idempotent (upsert). Ghi thật cần service key (server).
- ⏳ E6.3 trang IC heatmap (cần data); E6.5 wire vào cron_weekly (NEEDS-APPROVAL, như E1.8).

**⚠️ Fact:** gate_matrix có **6 regime** (UP/SIDE/RECOV/DOWN/DEEP/UNKNOWN), không phải 4 như migration 0001 comment.

## 4f. E3 + E6.3 (Read UI, DONE code — 2026-09-12)

- ✅ `today`: đọc v4_runs (run mới nhất) + v4_signals; stat cards + bảng SignalsTable; version động.
- ✅ `history`: filter ngày/mã/decision (client HistoryFilters) + phân trang server-side range(50)+count.
- ✅ `history/[id]`: drill-down breakdown (s_*/norms/gates/ranks/shadow/trade-levels) + outcome forward. React escape → XSS-safe.
- ✅ `ic`: heatmap table factor×horizon theo version, màu diverging theo IC.
- ✅ Helper `lib/format.ts` + `components/{signals-table,history-filters}.tsx`.
- ⏳ Tất cả hiển thị **empty-state** tới khi có data thật (sync + IC export chạy). Chưa app-test/visual-qa (cần app chạy).

## 4g. Build verified + fix Vercel (2026-09-12)
- ✅ `npm install` + `tsc --noEmit` sạch + `next build` **PASS** tại chỗ (10 route, static/dynamic đúng, middleware OK).
- ✅ Sửa lỗi build: nav.tsx (bỏ as const), server/middleware setAll annotate CookieToSet.
- ✅ Vá bảo mật: Next 15.1.6 → 15.5.25 (CVE-2025-66478); +package-lock.json.
- ⚠️ Fix ở nhánh `claude/bold-pascal-768taz` — cần **merge lại vào main** để Vercel redeploy thành công (lần build lỗi trước chạy trên main@190b1d5 chưa có fix).

## 4h. E7 — Buy Board & Chart (DONE code, build PASS — 2026-09-15)

- ✅ Trang `/buy`: list BUY/STRONG BUY (run mới nhất, sort score) bên trái + chart bên phải (master-detail, mobile xếp dọc).
- ✅ Chart nến custom SVG (`price-chart.tsx`): nến daily dựng từ giá snap (ADR-010) + overlay entry/stop/tp1/tp2 + ★ highlight khi high≥TP + strip intraday ngày ra tín hiệu. Nhãn rõ "không phải tick OHLC đầy đủ".
- ✅ `lib/chart.ts` (buildCandles/tpHit) + `buy-board.tsx` (fetch chuỗi giá qua supabase client, chỉ đọc `price:breakdown->>price` cho nhẹ).
- ✅ Nav thêm mục "Mua". `tsc --noEmit` + `next build` PASS (route /buy 3.72kB).
- ⏳ Cần **merge → main** để Vercel deploy; app-test/visual-qa sau khi live.

## 4i. Phân tích tín hiệu — đồng bộ với Buy (2026-10-09)

- ✅ Root cause: tab Buy đọc `v4_signals` đến 2026-10-08; tab Phân tích chỉ đọc outcome đã đủ 10 phiên trong `v4_signal_results`, tối đa 2026-09-24. Cron weekly tạo outcome nhưng trước đây không sync Supabase ngay.
- ✅ Migration `0018_signal_analysis_feed.sql`: view `security_invoker` giữ snapshot BUY mới nhất theo mã/ngày và left-join outcome; tín hiệu chưa chín vẫn hiện nhưng outcome để null.
- ✅ `/phan-tich` phân trang qua giới hạn PostgREST 1.000 dòng và tách mẫu đã chín khỏi mẫu đang chờ khi tính tỷ lệ TP/SL.
- ✅ `cron_weekly.yml` sync outcome lên Supabase sau khi commit/push ledger thành công.
- ✅ Live verified: 1.426 mã-ngày đến 2026-10-08; 831 đã chín, 595 chờ; tháng 10 có 341 dòng chờ. TypeScript PASS; Next production build exit 0 (local ESLint cảnh báo thiếu plugin `react-hooks`).

## 4j. Tab IC — chuẩn hóa diễn giải và xác minh IC ngành (2026-10-09)

- ✅ Toàn bộ chuỗi tiếng Việt lỗi mã hóa trong trang IC đã được sửa.
- ✅ Các phần diễn giải phía dưới được chuyển thành bảng trong `<details>` và mặc định thu gọn; bảng scoring và IC theo ngành vẫn ở phía trên.
- ✅ UI phân biệt lỗi truy vấn Supabase với trạng thái không có dữ liệu, tránh báo nhầm “chưa đủ phiên”.
- ✅ Supabase live: scoring v4.18 có 15 ngành ở đủ horizon 1/3/5/10; `n` theo ngành từ 31 đến 558. Quyền đọc đã xác minh bằng role `authenticated`.
- ✅ UI chỉ tải 60 dòng IC ngành của version hiện tại và đặt bảng ngay sau scoring hiện tại; tránh bị khuất sau nhiều version và tránh giới hạn PostgREST.
- ✅ Chỉ render version có IC official, vì vậy v4.6 (0 dòng `v4_ic_metrics`) không còn xuất hiện dưới dạng bảng trống.
- ✅ Thêm bảng thuật ngữ chuyên môn (Spearman, IC, Williams %R, Bollinger, EMA, RS, breakout, order flow, t-stat, R², horizon, n) sau bảng số lượng mẫu; mặc định thu gọn.
- ✅ `tsc --noEmit` PASS; Next production build PASS. Build còn cảnh báo môi trường local thiếu `eslint-plugin-react-hooks`, không chặn compile.

## 4k. IC ngành theo version/category + đồng bộ chọn mã (2026-10-09)

- ✅ Ô tìm mã và ô chọn mã trong tab Phân tích dùng chung state: tìm/chọn kết quả sẽ đổi ngay mã đang xem; ô chọn mã đặt ngay sau ô tìm kiếm và bỏ dropdown trùng lặp phía dưới.
- ✅ Migration `0019_ic_by_industry_factor_ver.sql` tạo view `v4_ic_by_industry_factor_ver` với `security_invoker`, tính Spearman IC theo `version × category × industry × horizon`.
- ✅ IC theo ngành hiển thị 5 version official (`v4.18`, `v4.17`, `v4.9`, `v4.8`, `v4.1`) và 7 category (`score_trade`, mean reversion, breakout, flow, fundamental, growth, context).
- ✅ Mỗi version và category là một bảng `<details>` collapse/expand; version hiện tại và `score_trade` mở mặc định, các phần còn lại thu gọn.
- ✅ Supabase live đã có đủ 7 category ở mọi version official; view mới không phát sinh cảnh báo Security Advisor. `tsc --noEmit` và Next production build PASS; cảnh báo local thiếu `eslint-plugin-react-hooks` vẫn không chặn build.

## 4l. Ổn định IC ngành và collapse toàn bảng scoring (2026-10-09)

- ✅ Root cause xác minh: mỗi version của view IC ngành mất khoảng 8,7 giây trước tối ưu; 5 truy vấn song song có thể lỗi/timeout riêng lẻ, trong khi UI cũ âm thầm lọc bỏ version lỗi nên danh sách thay đổi giữa các lần tải.
- ✅ Thêm index `idx_v4_signals_scoring_version`; đo lại truy vấn v4.18 còn khoảng 2,4 giây. DDL đã apply live và lưu tại migration `0020_index_signals_scoring_version.sql`.
- ✅ Query IC ngành retry một lần; UI luôn giữ đủ header của mọi version official và hiển thị lỗi ngay trong version tương ứng thay vì âm thầm thay bằng version khác.
- ✅ Toàn bộ bảng IC scoring có nút collapse/expand riêng; version hiện tại mở mặc định, version cũ thu gọn.
- ✅ TypeScript PASS; Next production build PASS. Supabase Advisor không phát sinh cảnh báo mới từ index.

---
## 5. Việc kế tiếp (next actions)

1. **Owner (thủ công)**: set secret GH `SUPABASE_SERVICE_ROLE_KEY` + merge branch → main → data tự chảy (E1.9).
2. **Owner**: `cd web && npm install && npm run dev` verify build + visual-qa E2.6; tạo user owner trong Supabase Auth để test /config gate.
3. **E3** — Read Dashboards (today/history/drill-down) — cần data thật (sau khi sync chạy).

---

## 6. Rào chắn an toàn đang hiệu lực
- Chỉ chạm bảng `v4_*` trên Supabase (không phá app dùng chung).
- Không sửa `steps/`/`utils/`/n8n khi chưa duyệt (đặc biệt E5).
- Secret (`service_role`, `GITHUB_TOKEN`) chỉ server.
- Con số điểm/IC chính thức chỉ từ Python; `simulate.ts` = simulation.
