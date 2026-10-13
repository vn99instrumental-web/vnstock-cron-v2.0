-- Cache the JWT lookup once per statement instead of evaluating it per row.
drop policy if exists app_settings_owner_write on public.app_settings;
create policy app_settings_owner_write on public.app_settings
  for update to authenticated
  using      ((select auth.jwt()) ->> 'email' = 'vn99instrumental@gmail.com')
  with check ((select auth.jwt()) ->> 'email' = 'vn99instrumental@gmail.com');