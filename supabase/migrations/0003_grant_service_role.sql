-- 0003_grant_service_role.sql — cấp lại quyền ghi cho service_role trên 5 bảng v4_*.
--
-- Bối cảnh: project mcaqnaomzoqgxccdgvls đã thu hồi grant mặc định của service_role
-- (has_schema_privilege('service_role','public','USAGE') = false), nên dù service_role
-- bypass RLS, mọi INSERT/UPDATE qua PostgREST vẫn bị:
--   HTTP 403 {"code":"42501","message":"permission denied for schema public"}
-- (phát hiện khi chạy workflow sync_supabase — đọc 23.170 signals OK nhưng ghi fail).
--
-- Fix: cấp USAGE schema + SELECT/INSERT/UPDATE/DELETE trên ĐÚNG 5 bảng của app.
-- KHÔNG đụng bảng app khác (never-do #7). Các bảng v4_* dùng GENERATED ALWAYS AS IDENTITY
-- nên không cần grant sequence riêng.

grant usage on schema public to service_role;

grant select, insert, update, delete on
  public.v4_runs,
  public.v4_signals,
  public.v4_outcomes,
  public.v4_scoring_configs,
  public.v4_ic_metrics
to service_role;
