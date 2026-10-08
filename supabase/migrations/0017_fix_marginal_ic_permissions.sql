-- 0017_fix_marginal_ic_permissions.sql — repair writer grants and secure public reads.
--
-- Migration 0016 created v4_marginal_ic after the original service_role grants,
-- so GitHub Actions could compute the rows but PostgREST rejected the upsert with
-- PostgreSQL 42501. Keep writes server-only and preserve the dashboard's public
-- read access behind an explicit RLS policy.

begin;

grant usage on schema public to service_role;

grant select, insert, update, delete
on table public.v4_marginal_ic
to service_role;

alter table public.v4_marginal_ic enable row level security;

drop policy if exists "read v4_marginal_ic" on public.v4_marginal_ic;
create policy "read v4_marginal_ic"
on public.v4_marginal_ic
for select
to anon, authenticated
using (true);

commit;
