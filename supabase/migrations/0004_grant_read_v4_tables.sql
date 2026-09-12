-- 0004_grant_read_v4_tables.sql — cấp SELECT tầng-bảng cho anon/authenticated.
--
-- Bối cảnh: migration 0001 đã tạo RLS policy 'for select ... using (true)' nhưng
-- project đã thu hồi GRANT mặc định ở tầng bảng → anon/authenticated KHÔNG có
-- quyền SELECT. Hậu quả: web (khóa anon) đọc ra 0 dòng dù bảng có 23.170 signals.
-- (RLS policy chỉ lọc dòng; vẫn cần GRANT SELECT tầng bảng thì role mới đọc được.)
--
-- Fix: cấp SELECT đúng ý policy 0001 — public read cho runs/signals/outcomes/ic;
-- config chỉ authenticated. KHÔNG cấp INSERT/UPDATE (ghi vẫn chỉ service_role).

grant select on
  public.v4_runs,
  public.v4_signals,
  public.v4_outcomes,
  public.v4_ic_metrics
to anon, authenticated;

grant select on public.v4_scoring_configs to authenticated;
