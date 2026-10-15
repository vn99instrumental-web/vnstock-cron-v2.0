-- Keep bounded retention reliable behind PostgREST's default role timeout.
-- The heavy orphan-outcome anti-join uses a small indexed temp table, and the
-- recurring maintenance RPC receives an explicit function-level timeout.

begin;

create or replace function public.prune_v4_legacy_intraday()
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog, public
set statement_timeout = '60s'
as $$
declare
  legacy_versions constant text[] := array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3'];
  signal_rows_after bigint;
  outcome_rows_after bigint;
  run_rows_after bigint;
  signal_rows_removed bigint := 0;
  outcome_rows_removed bigint := 0;
  run_rows_removed bigint := 0;
begin
  create temporary table keep_v4_legacy_runs (
    run_id text primary key
  ) on commit drop;

  insert into keep_v4_legacy_runs (run_id)
  select run_id
  from (
    select distinct on (scoring_version, signal_date)
      scoring_version, signal_date, run_id
    from public.v4_signals
    where scoring_version = any (legacy_versions)
      and run_id is not null
    order by scoring_version, signal_date, snap_time desc, id desc
  ) daily_close;

  insert into keep_v4_legacy_runs (run_id)
  select run_id
  from (
    select distinct on (scoring_version, signal_date)
      scoring_version, signal_date, run_id
    from public.v4_signals
    where scoring_version = any (legacy_versions)
      and decision in ('BUY', 'STRONG BUY')
      and run_id is not null
    order by scoring_version, signal_date, snap_time desc, id desc
  ) daily_buy
  on conflict (run_id) do nothing;

  delete from public.v4_signals signal
  where signal.scoring_version = any (legacy_versions)
    and not exists (
      select 1 from keep_v4_legacy_runs kept
      where kept.run_id = signal.run_id
    );
  get diagnostics signal_rows_removed = row_count;

  create temporary table keep_v4_legacy_predictions (
    scoring_version text not null,
    pred_id text not null,
    primary key (scoring_version, pred_id)
  ) on commit drop;

  insert into keep_v4_legacy_predictions (scoring_version, pred_id)
  select distinct signal.scoring_version, signal.breakdown->>'pred_id'
  from public.v4_signals signal
  where signal.scoring_version = any (legacy_versions)
    and signal.breakdown->>'pred_id' is not null;

  delete from public.v4_outcomes outcome
  where outcome.scoring_version = any (legacy_versions)
    and not exists (
      select 1 from keep_v4_legacy_predictions kept
      where kept.scoring_version = outcome.scoring_version
        and kept.pred_id = outcome.pred_id
    );
  get diagnostics outcome_rows_removed = row_count;

  delete from public.v4_runs run
  where run.scoring_version = any (legacy_versions)
    and not exists (
      select 1 from public.v4_signals signal
      where signal.run_id = run.run_id
    );
  get diagnostics run_rows_removed = row_count;

  select count(*) into signal_rows_after
  from public.v4_signals
  where scoring_version = any (legacy_versions);
  select count(*) into outcome_rows_after
  from public.v4_outcomes
  where scoring_version = any (legacy_versions);
  select count(*) into run_rows_after
  from public.v4_runs
  where scoring_version = any (legacy_versions);

  return jsonb_build_object(
    'signals_before', signal_rows_after + signal_rows_removed,
    'signals_after', signal_rows_after,
    'signals_removed', signal_rows_removed,
    'outcomes_before', outcome_rows_after + outcome_rows_removed,
    'outcomes_after', outcome_rows_after,
    'outcomes_removed', outcome_rows_removed,
    'runs_before', run_rows_after + run_rows_removed,
    'runs_after', run_rows_after,
    'runs_removed', run_rows_removed,
    'completed_at', clock_timestamp()
  );
end;
$$;

revoke all on function public.prune_v4_legacy_intraday() from public, anon, authenticated;
grant execute on function public.prune_v4_legacy_intraday() to service_role;
comment on function public.prune_v4_legacy_intraday() is
  'Retains full intraday for v4.18/v4.17 and daily close plus latest BUY run for v4.19-shadow and older review versions.';

alter function public.prune_v4_orphan_runs() set statement_timeout = '60s';

commit;
