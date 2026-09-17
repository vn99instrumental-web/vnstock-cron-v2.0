-- 0011_app_settings.sql — cài đặt cấp app do owner điều khiển (runtime, không cần redeploy).
--
-- Mục đích: cờ require_login — bật thì mọi trang yêu cầu đăng nhập mới xem;
-- tắt (mặc định) thì app công khai như hiện tại.
--
-- Bảng singleton (chỉ 1 dòng id=true). Cờ này KHÔNG nhạy cảm (chỉ cho biết app
-- có yêu cầu login hay không) → cho anon/authenticated SELECT để middleware đọc
-- được bằng anon key TRƯỚC khi user đăng nhập. GHI chỉ qua service_role
-- (bypass RLS) từ route /api/settings đã kiểm owner — KHÔNG cấp INSERT/UPDATE.

create table if not exists public.app_settings (
  id            boolean primary key default true check (id),  -- singleton
  require_login boolean not null default false,
  updated_at    timestamptz not null default now(),
  updated_by    text
);

insert into public.app_settings (id, require_login)
  values (true, false)
  on conflict (id) do nothing;

alter table public.app_settings enable row level security;

drop policy if exists app_settings_read on public.app_settings;
create policy app_settings_read on public.app_settings
  for select to anon, authenticated using (true);

grant select on public.app_settings to anon, authenticated;
