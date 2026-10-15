-- Keep the daily serving refresh within the Database REST API execution window.
-- Factor-pair correlation is exploratory and can exceed 60 seconds on the free
-- database; preserve its last successful snapshot instead of blocking all
-- critical daily snapshots.

begin;

create or replace function public.refresh_v4_dashboard_snapshots()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
set statement_timeout = '60s'
as $$
declare
  refreshed timestamptz := clock_timestamp();
  versions_count integer := 0;
begin
  delete from public.v4_analysis_diagnostics_snapshot
  where kind in ('factor', 'split');

  insert into public.v4_analysis_diagnostics_snapshot
    (scoring_version, kind, factor, grp, n, corr_ret5, corr_win, computed_at)
  select scoring_version, 'factor', factor, grp, n, corr_ret5, corr_win, refreshed
  from public.v4_hit_factor_corr;

  insert into public.v4_analysis_diagnostics_snapshot
    (scoring_version, kind, dim, bucket, factor, grp, n, corr_ret5, corr_win, computed_at)
  select scoring_version, 'split', dim, bucket, factor, grp, n, corr_ret5, corr_win, refreshed
  from public.v4_hit_factor_corr_split;

  insert into public.v4_ic_daily_snapshot
    (snapshot_date, config_version, factor, horizon, ic, n, computed_at)
  select (computed_at at time zone 'Asia/Ho_Chi_Minh')::date,
         config_version, factor, horizon, ic, n, computed_at
  from public.v4_ic_metrics
  where config_version is not null
  on conflict (snapshot_date, config_version, factor, horizon)
  do update set ic = excluded.ic, n = excluded.n, computed_at = excluded.computed_at;

  delete from public.v4_ic_daily_snapshot
  where snapshot_date < (current_date - 400);

  delete from public.v4_dashboard_version_summary;
  insert into public.v4_dashboard_version_summary
    (scoring_version, signal_date_min, signal_date_max, signal_days, signal_rows,
     outcome_date_min, outcome_date_max, outcome_rows, latest_update, refreshed_at)
  with signal_stats as (
    select scoring_version, min(signal_date) signal_date_min, max(signal_date) signal_date_max,
           count(distinct signal_date)::integer signal_days, count(*) signal_rows,
           max(snap_time) latest_signal_update
    from public.v4_signals
    where scoring_version is not null
    group by scoring_version
  ), outcome_stats as (
    select scoring_version, min(signal_date) outcome_date_min, max(eval_date) outcome_date_max,
           count(*) outcome_rows, max(synced_at) latest_outcome_update
    from public.v4_outcomes
    where scoring_version is not null
    group by scoring_version
  )
  select s.scoring_version, s.signal_date_min, s.signal_date_max, s.signal_days, s.signal_rows,
         o.outcome_date_min, o.outcome_date_max, coalesce(o.outcome_rows, 0),
         greatest(s.latest_signal_update, o.latest_outcome_update), refreshed
  from signal_stats s
  left join outcome_stats o using (scoring_version);

  get diagnostics versions_count = row_count;
  return jsonb_build_object(
    'refreshed_at', refreshed,
    'diagnostics_rows', (select count(*) from public.v4_analysis_diagnostics_snapshot),
    'factor_rows', (select count(*) from public.v4_analysis_diagnostics_snapshot where kind = 'factor'),
    'split_rows', (select count(*) from public.v4_analysis_diagnostics_snapshot where kind = 'split'),
    'pair_rows_preserved', (select count(*) from public.v4_analysis_diagnostics_snapshot where kind = 'pair'),
    'version_rows', versions_count,
    'ic_history_rows', (select count(*) from public.v4_ic_daily_snapshot)
  );
end;
$$;

revoke all on function public.refresh_v4_dashboard_snapshots() from public, anon, authenticated;
grant execute on function public.refresh_v4_dashboard_snapshots() to service_role;
comment on function public.refresh_v4_dashboard_snapshots() is
  'Refreshes critical daily dashboard snapshots within 60s and preserves the last successful exploratory factor-pair snapshot.';

commit;
