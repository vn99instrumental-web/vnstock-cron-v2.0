-- Ensure daily retention also removes unreferenced runs for full-intraday versions.
create or replace function public.prune_v4_orphan_runs()
returns bigint
language sql
security invoker
set search_path = pg_catalog, public
as $$
  with deleted as (
    delete from public.v4_runs run
    where not exists (
      select 1 from public.v4_signals signal where signal.run_id = run.run_id
    )
    returning run.run_id
  )
  select count(*)::bigint from deleted;
$$;

revoke all on function public.prune_v4_orphan_runs() from public, anon, authenticated;
grant execute on function public.prune_v4_orphan_runs() to service_role;
comment on function public.prune_v4_orphan_runs() is
  'Deletes v4_runs rows that no longer have any serving signal.';