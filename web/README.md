# VNStock Signals — Web (E2 Foundation)

App web hiển thị & điều chỉnh pipeline chấm điểm cổ phiếu VN (`v2f_v4`). Next.js (App Router) + TypeScript + Tailwind v4 + Supabase.

## Chạy local

```bash
cd web
cp .env.local.example .env.local   # điền anon key + owner email (KHÔNG điền service key ở E2)
npm install
npm run dev                        # http://localhost:3000
```

## Cấu trúc

```
app/
  layout.tsx                 # root (html/body, globals.css)
  page.tsx                   # → redirect /today
  (dashboard)/
    layout.tsx               # shell: sidebar nav + header (version badge động)
    today/ history/ history/[id]/ ic/ config/   # 5 route (config gate owner)
  login/                     # đăng nhập owner (email+password)
  auth/callback/route.ts     # exchange code (magic-link/OAuth — để sẵn)
lib/supabase/
  client.ts                  # browser (anon key)
  server.ts                  # server (anon + cookie session) + getUser/isOwner
  middleware.ts              # refresh session + gate /config
middleware.ts                # entrypoint middleware
components/                  # nav, version-badge, sign-out, ui primitives
```

## Bảo mật (ADR-005/007)

- **Chỉ anon/publishable key** ra client. `SUPABASE_SERVICE_ROLE_KEY` + `GITHUB_TOKEN`
  **không** dùng ở E2 — chỉ xuất hiện ở route ghi đặc quyền (E4 Promote), server-only.
- `/config` + Promote: gate bằng Supabase Auth **đơn owner** (`NEXT_PUBLIC_OWNER_EMAIL`),
  kiểm ở cả middleware lẫn server component.
- Public read: today/history/ic (RLS đã cho anon select).

## Version-agnostic (golden rule #2)

`components/version-badge.tsx` đọc `scoring_version`/`gate_version` **động** từ run mới nhất
(`v4_runs`). Không hardcode version trong UI.

## Trạng thái

E2 = foundation (scaffold + auth + shell). Trang data thật (bảng tín hiệu, filter, drill-down,
heatmap IC) dựng ở **E3/E6**. Bảng Supabase còn rỗng cho tới khi sync (E1.8) chạy.
