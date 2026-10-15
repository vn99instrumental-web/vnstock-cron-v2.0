-- Bound Supabase serving storage while keeping the Git ledger lossless.
-- Full intraday: v4.18/v4.17. Older review versions retain the final run and
-- final BUY-bearing run of every day so Buy keeps its complete drill-down.

create or replace function public.prune_v4_legacy_intraday()
returns jsonb language plpgsql security invoker set search_path = pg_catalog, public
as $$
declare
  signal_rows_before bigint; signal_rows_after bigint;
  outcome_rows_before bigint; outcome_rows_after bigint;
  run_rows_before bigint; run_rows_after bigint;
begin
  select count(*) into signal_rows_before from public.v4_signals where scoring_version = any (array['v4.9','v4.8','v4.1','v2.3']);
  select count(*) into outcome_rows_before from public.v4_outcomes where scoring_version = any (array['v4.9','v4.8','v4.1','v2.3']);
  select count(*) into run_rows_before from public.v4_runs where scoring_version = any (array['v4.9','v4.8','v4.1','v2.3']);

  create temporary table keep_v4_legacy_runs (run_id text primary key) on commit drop;
  insert into keep_v4_legacy_runs (run_id)
  select run_id from (
    select distinct on (scoring_version, signal_date) scoring_version, signal_date, run_id
    from public.v4_signals
    where scoring_version = any (array['v4.9','v4.8','v4.1','v2.3']) and run_id is not null
    order by scoring_version, signal_date, snap_time desc, id desc
  ) daily_close;
  insert into keep_v4_legacy_runs (run_id)
  select run_id from (
    select distinct on (scoring_version, signal_date) scoring_version, signal_date, run_id
    from public.v4_signals
    where scoring_version = any (array['v4.9','v4.8','v4.1','v2.3'])
      and decision in ('BUY','STRONG BUY') and run_id is not null
    order by scoring_version, signal_date, snap_time desc, id desc
  ) daily_buy on conflict (run_id) do nothing;

  delete from public.v4_signals signal
  where signal.scoring_version = any (array['v4.9','v4.8','v4.1','v2.3'])
    and not exists (select 1 from keep_v4_legacy_runs kept where kept.run_id = signal.run_id);
  delete from public.v4_outcomes outcome
  where outcome.scoring_version = any (array['v4.9','v4.8','v4.1','v2.3'])
    and not exists (
      select 1 from public.v4_signals signal
      where signal.scoring_version = outcome.scoring_version and signal.breakdown->>'pred_id' = outcome.pred_id
    );
  delete from public.v4_runs run
  where run.scoring_version = any (array['v4.9','v4.8','v4.1','v2.3'])
    and not exists (select 1 from public.v4_signals signal where signal.run_id = run.run_id);

  select count(*) into signal_rows_after from public.v4_signals where scoring_version = any (array['v4.9','v4.8','v4.1','v2.3']);
  select count(*) into outcome_rows_after from public.v4_outcomes where scoring_version = any (array['v4.9','v4.8','v4.1','v2.3']);
  select count(*) into run_rows_after from public.v4_runs where scoring_version = any (array['v4.9','v4.8','v4.1','v2.3']);
  return jsonb_build_object(
    'signals_before',signal_rows_before,'signals_after',signal_rows_after,'signals_removed',signal_rows_before-signal_rows_after,
    'outcomes_before',outcome_rows_before,'outcomes_after',outcome_rows_after,'outcomes_removed',outcome_rows_before-outcome_rows_after,
    'runs_before',run_rows_before,'runs_after',run_rows_after,'runs_removed',run_rows_before-run_rows_after,'completed_at',clock_timestamp()
  );
end;
$$;
revoke all on function public.prune_v4_legacy_intraday() from public, anon, authenticated;
grant execute on function public.prune_v4_legacy_intraday() to service_role;
comment on function public.prune_v4_legacy_intraday() is
  'Retains full intraday for v4.18/v4.17 and daily close plus latest BUY run for older review versions.';