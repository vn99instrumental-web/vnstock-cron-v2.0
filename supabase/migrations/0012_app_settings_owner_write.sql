-- 0012_app_settings_owner_write.sql — cho OWNER ghi app_settings trực tiếp
-- bằng session (browser client), không cần service_role.
--
-- Lý do: route handler /api/settings đọc session không ổn định (getUser trong
-- route trả null trong vài trường hợp) + phụ thuộc SUPABASE_SERVICE_ROLE_KEY.
-- Ghi trực tiếp qua client đã đăng nhập là path mọi trang dashboard dùng, ổn định.
--
-- Bảo mật: chỉ authenticated + đúng email owner mới UPDATE được (RLS + JWT email).
-- Email owner cố định trong policy (ACL, không phải tham số scoring). Nếu đổi
-- owner, cập nhật policy này.

grant update on public.app_settings to authenticated;

drop policy if exists app_settings_owner_write on public.app_settings;
create policy app_settings_owner_write on public.app_settings
  for update to authenticated
  using      (auth.jwt() ->> 'email' = 'vn99instrumental@gmail.com')
  with check (auth.jwt() ->> 'email' = 'vn99instrumental@gmail.com');
