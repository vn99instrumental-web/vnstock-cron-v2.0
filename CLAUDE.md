# CLAUDE.md — Hiến pháp dự án (Claude Code đọc mỗi phiên)

> Đây là app web hiển thị & điều chỉnh cho pipeline chấm điểm cổ phiếu VN
> `vn99instrumental-web/vnstock-cron-v2.0`. App **không** thay bộ não Python —
> app là lớp truy vấn (Supabase) + tương tác (Next.js/Vercel).

---

## 1. Bối cảnh & stack

- **Repo:** `vn99instrumental-web/vnstock-cron-v2.0` (public). App sống trong subfolder `web/`.
- **Stack:** Next.js (App Router) + TypeScript · Supabase (Postgres 17 + Auth + RLS) · Vercel · Recharts.
- **Pipeline Python:** giữ nguyên, chạy trên GitHub Actions, trigger bởi n8n 5×/ngày. **Nguồn chân lý duy nhất** cho mọi con số điểm/IC.
- **Nguồn dữ liệu:** GitHub JSONL ledger (`output/history/v2f_predictions_v4/`, `v2f_outcomes_v4/`) = sổ cái append-only. Supabase = bản mirror để app query.

## 2. Golden rules (bắt buộc, không thương lượng)

1. **Evidence-first.** Trước khi kết luận, đọc data/HEAD thật. Không suy diễn từ trí nhớ hay tài liệu cũ. `git rev-parse HEAD` + đọc file gốc trước mọi thay đổi.
2. **Version-agnostic.** App đọc `SCORING_VERSION`/`GATE_VERSION` **động** từ output pipeline. **Không hardcode** version, weight, hay gate trong UI.
3. **Một nguồn chân lý cho scoring.** Không reimplement công thức chấm điểm/IC bằng TS làm căn cứ chính thức. Con số chính thức luôn từ Python. `simulate.ts` chỉ ước lượng, phải dán nhãn "simulation".
4. **Shadow-first & one-change-per-cycle.** Thay đổi production scorer → shadow ≥30 phiên trước khi promote. Mỗi chu kỳ đúng 1 thay đổi. Bump `SCORING_VERSION` reset forward-validation bucket.
5. **Forward > backtest.** What-if/backtest chỉ là giả thuyết; forward outcomes mới quyết định.
6. **Hỏi trước khi động production.** Không sửa `steps/`, `utils/`, workflow n8n, hay commit vào repo mà chưa được duyệt. Giao **full-file** khi cần commit tay, không đưa diff rời rạc.
7. **Bảo mật.** `SUPABASE_SERVICE_ROLE_KEY` và `GITHUB_TOKEN` **chỉ** ở server (Vercel env / GH secret). Không bao giờ vào client bundle. Anon/publishable key mới được ra browser.
8. **Chất lượng code Python.** `py_compile` + AST validate trước khi giao bất kỳ file Python nào.
9. **Ngôn ngữ.** Nhãn UI tiếng Việt. Giữ nguyên tên chỉ báo kỹ thuật (RSI, MFI…). Giải thích tránh jargon.

## 3. Never-do

- ❌ Hardcode trọng số/gate/version trong `web/`.
- ❌ Tính IC "chính thức" bằng TS.
- ❌ Đẩy `service_role`/GitHub token ra client.
- ❌ Sửa file pipeline (`steps/`, `utils/`, `scripts/` cũ) hoặc n8n workflow khi chưa duyệt.
- ❌ Chấm lại lịch sử rồi coi là production; what-if phải tách bạch.
- ❌ Bật RLS cho bảng app khác mà thiếu policy (khóa app cũ của user).

## 4. Skill workflow (áp dụng triệt để)

Vòng đời cố định mỗi task:

| Bước | Skill | Kích hoạt khi |
|---|---|---|
| 1. Chốt yêu cầu, đào cạm bẫy | `grill-me` | Đầu mỗi epic / task mơ hồ |
| 2. Thiết kế UI | `frontend-design` | Trước khi code page/component mới (consume mockup Google Stitch nếu có) |
| 3. Implement | — | Full-file, dựa HEAD mới nhất |
| 4. Kiểm luồng | `app-test` | Sau feature/routing/form/auth/persistence |
| 5. Soi hiển thị/responsive | `visual-qa` | Sau đổi style/layout |
| 6. Rà bảo mật | `security-review` | Mọi code chạm auth/Supabase/API/secret/Promote/input ngoài |
| 7. Cập nhật trạng thái | `project-update` | Sau merge → refresh `PROJECT_STATE.md` |

**Cadence:** `grill-me` mở màn mỗi epic → `security-review` + `app-test` + `visual-qa` là cổng bắt buộc trước merge UI/nhạy cảm → `project-update` chốt sổ sau merge.

## 5. Cơ chế task & cập nhật

- **`PROJECT_STATE.md`** = nguồn chân lý trạng thái build. Do `project-update` tái sinh từ chứng cứ repo. Đọc đầu mỗi phiên.
- **`docs/build/TASKS.md`** = backlog epic→task. Mỗi task: ID · skill · Definition of Done · status · dependency. Cập nhật status ngay khi xong task.
- **`docs/build/DECISIONS.md`** = ADR, nhật ký quyết định kiến trúc (append-only).
- **`docs/build/PRD.md`** = yêu cầu sản phẩm & acceptance criteria. Không code trái PRD; nếu cần lệch, ghi ADR trước.

## 6. Bản đồ repo

```
CLAUDE.md · PROJECT_STATE.md
docs/build/{PRD,PLAN,TASKS,DECISIONS}.md
config/scoring/{active.json, schema.json}     # active.json do Promote ghi; schema.json validate
supabase/migrations/*.sql
scripts/sync_supabase.py                       # [E1] upsert JSONL → Supabase
scripts/export_ic_to_supabase.py               # [E6] evaluator ghi ic_metrics
steps/v2f_step_scoring_v4.py                   # [E5, CẦN DUYỆT] đọc config từ active.json + fallback
web/                                           # Next.js app
  app/(dashboard)/{today,history,history/[id],config,ic}
  app/api/promote/route.ts                     # server-only: commit active.json
  lib/supabase/{server,client}.ts · lib/scoring/simulate.ts
  components/ · middleware.ts
```

## 7. Env vars

| Biến | Nơi | Bí mật? |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | client + server | Không |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` (publishable) | client + server | Không |
| `SUPABASE_SERVICE_ROLE_KEY` | server / Python | **CÓ** |
| `GITHUB_TOKEN` (fine-grained PAT, contents rw) | server (Promote) / GH Actions | **CÓ** |
| `GITHUB_REPO` = `vn99instrumental-web/vnstock-cron-v2.0` | server | Không |
| `CONFIG_PATH` = `config/scoring/active.json` | server | Không |
