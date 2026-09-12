# PROJECT_STATE.md — Trạng thái build (nguồn chân lý)

> Tái sinh từ **chứng cứ repo thật** (không suy diễn). Đọc đầu mỗi phiên.
> Do skill `project-update` cập nhật sau mỗi merge.

**Cập nhật:** 2026-09-12 (grill vòng 2) · **HEAD gốc:** `38de5bb` · **Branch:** `claude/bold-pascal-768taz` · **PRD:** v2.0 GRILLED

---

## 1. Ta đang ở đâu

**Phase 0 — Foundation (E0), đang chốt.** Repo đang ở giai đoạn tài liệu build; **chưa có** `web/`, chưa có `scripts/sync_supabase.py`, chưa có `config/scoring/`. Pipeline Python đã đầy đủ và đang chạy production.

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

## 5. Việc kế tiếp (next actions)

1. **E0.7** — commit + push docs lên `claude/bold-pascal-768taz`.
2. **E1** — chốt ADR-002 + ADR-006 → viết `sync_supabase.py` (có data thật lên bảng).
3. **E2** — scaffold `web/` (song song E1).

---

## 6. Rào chắn an toàn đang hiệu lực
- Chỉ chạm bảng `v4_*` trên Supabase (không phá app dùng chung).
- Không sửa `steps/`/`utils/`/n8n khi chưa duyệt (đặc biệt E5).
- Secret (`service_role`, `GITHUB_TOKEN`) chỉ server.
- Con số điểm/IC chính thức chỉ từ Python; `simulate.ts` = simulation.
