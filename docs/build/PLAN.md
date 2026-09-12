# PLAN — Lộ trình build VNStock Signals App

> Lộ trình phân pha, dependency, và cadence skill. Đọc kèm `PRD.md` (yêu cầu) + `TASKS.md` (backlog task).
> **Nguyên tắc:** one-change-per-cycle · shadow-first · forward > backtest · hỏi trước khi động production.

**Version:** 1.0 · **Ngày:** 2026-09-12 · **HEAD gốc:** `38de5bb`

---

## 1. Bản đồ phụ thuộc (dependency graph)

```
E0 Foundation (docs)
 ├─▶ E1 Data Sync ─────────────┐
 └─▶ E2 Web Foundation ────────┤
                               ├─▶ E3 Read Dashboards (cần E1 data + E2 khung)
                               ├─▶ E4 Config & Promote (cần E2 auth + E3 UX + schema)
                               │      └─▶ E5 Scorer config-driven (cần active.json shape từ E4 + DUYỆT)
                               └─▶ E6 IC Evaluator (cần E1 outcomes) ─▶ trang IC (cần E2)
```

**Đường găng (critical path):** E0 → E1 → E3 (data lên UI sớm để có phản hồi thực).
**Nhánh song song an toàn:** E2 (khung web) chạy song song E1 (sync) vì độc lập.

---

## 2. Phân pha (phases)

### Phase 0 — Nền móng *(đang làm)*
- **Epic:** E0.
- **Ra được:** 5 docs build + PROJECT_STATE + ADR khởi tạo.
- **Cổng ra:** connection verified + docs khớp HEAD → `project-update`.

### Phase 1 — Có data thật trên bảng
- **Epic:** E1 (Data Sync).
- **Quyết định chặn:** ADR-002 schema outcomes (wide/long) — chốt TRƯỚC khi code sync.
- **Ra được:** `sync_supabase.py` idempotent; `v4_signals/outcomes/runs` có data tháng gần nhất.
- **Cổng ra:** row count khớp ledger + re-run không nhân đôi → `security-review` + `app-test`.

### Phase 2 — Khung web + auth
- **Epic:** E2 (Web Foundation).
- **Ra được:** `web/` chạy, auth gate, lib/supabase đúng lớp key, middleware.
- **Cổng ra:** service key không vào client bundle → `security-review` + `visual-qa`.

### Phase 3 — Đọc & hiển thị
- **Epic:** E3 (Today/History).
- **Ra được:** 3 trang đọc data, version động, drill-down breakdown.
- **Cổng ra:** khớp run mới nhất + states đầy đủ → `app-test` + `visual-qa`.

### Phase 4 — Điều chỉnh scorer (vòng nhạy cảm)
- **Epic:** E4 (Config & Promote) → E5 (Scorer đọc active.json, **CẦN DUYỆT**).
- **Ra được:** editor + simulate(nhãn) + promote server-only + scorer fallback-safe.
- **Cổng ra:** security-review bắt buộc; E5 hỏi duyệt + shadow ≥30 phiên trước promote.

### Phase 5 — Chất lượng nhân tố
- **Epic:** E6 (IC Evaluator) + trang IC.
- **Ra được:** rank-IC per factor×horizon → `v4_ic_metrics` → trang IC.
- **Cổng ra:** IC tính bằng Python, idempotent → `app-test` + `visual-qa`.

---

## 3. Cadence skill (bắt buộc mỗi vòng)

| Thời điểm | Skill | Ghi chú |
|---|---|---|
| Mở mỗi epic / task mơ hồ | `grill-me` | Chốt yêu cầu, đào cạm bẫy trước khi code |
| Trước code UI mới | `frontend-design` | Consume mockup Google Stitch nếu có |
| Sau feature/routing/form/auth/persistence | `app-test` | Kiểm luồng |
| Sau đổi style/layout | `visual-qa` | Soi hiển thị/responsive |
| Mọi code chạm auth/Supabase/API/secret/Promote/input ngoài | `security-review` | Cổng cứng trước merge |
| Sau merge | `project-update` | Tái sinh `PROJECT_STATE.md` |

**Cổng merge (UI/nhạy cảm):** `security-review` + `app-test` + `visual-qa` phải pass.

---

## 4. Nguyên tắc thực thi (bám golden rules)

1. **Evidence-first:** mỗi task đọc HEAD thật + file gốc trước khi sửa. `git rev-parse HEAD`.
2. **One-change-per-cycle:** mỗi vòng đúng 1 thay đổi production scorer; UI cảnh báo nếu vi phạm.
3. **Shadow-first:** đổi scorer → shadow ≥30 phiên → mới promote. Bump `SCORING_VERSION` reset forward bucket.
4. **Full-file khi commit tay:** không đưa diff rời rạc.
5. **Hỏi trước production:** không sửa `steps/`, `utils/`, workflow n8n khi chưa duyệt (đặc biệt E5).
6. **Không phá app dùng chung:** chỉ chạm bảng `v4_*` trên Supabase.

---

## 5. Milestone & cổng quyết định

| Milestone | Điều kiện đạt | Quyết định kế tiếp |
|---|---|---|
| M0 Foundation | Docs + connection verified | Bắt đầu E1/E2 song song |
| M1 Data live | Sync idempotent, data trên bảng | Chốt ADR-002; mở E3 |
| M2 Web live | Khung + auth + secret an toàn | Mở E3/E4 |
| M3 Read UI | Today/History/drill-down đạt DoD | Mở E4 |
| M4 Config loop | Promote server-only an toàn | **Hỏi duyệt** mở E5 |
| M5 Scorer dynamic | scoring_v4 fallback-safe, shadow chạy | Đủ 30 phiên → promote thật |
| M6 IC | v4_ic_metrics + trang IC | v2.0 GA |
