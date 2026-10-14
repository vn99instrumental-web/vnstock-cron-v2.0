-- Precompute dashboard diagnostics after the daily sync so Vercel only reads small serving tables.
begin;

create index if not exists v4_signals_pred_version_idx
  on public.v4_signals ((breakdown->>'pred_id'), scoring_version);

create or replace view public.v4_signal_analysis_dashboard
with (security_invoker = true)
as
select feed.*, signal.score_trade
from public.v4_signal_analysis_feed feed
left join lateral (
  select source.score_trade
  from public.v4_signals source
  where source.breakdown->>'pred_id' = feed.pred_id
    and source.scoring_version = feed.scoring_version
  order by source.snap_time desc, source.id desc
  limit 1
) signal on true;

revoke all on public.v4_signal_analysis_dashboard from anon, authenticated;
grant select on public.v4_signal_analysis_dashboard to anon, authenticated;

create table if not exists public.v4_analysis_diagnostics_snapshot (
  id bigint generated always as identity primary key,
  scoring_version text not null,
  kind text not null check (kind in ('factor', 'pair', 'split')),
  dim text,
  bucket text,
  factor text not null,
  factor_b text,
  grp text,
  n integer not null default 0,
  corr_ret5 numeric,
  corr_win numeric,
  corr numeric,
  computed_at timestamptz not null default now()
);
create index if not exists v4_analysis_diag_lookup_idx
  on public.v4_analysis_diagnostics_snapshot(scoring_version, kind, dim, bucket);

create table if not exists public.v4_ic_daily_snapshot (
  snapshot_date date not null,
  config_version text not null,
  factor text not null,
  horizon integer not null check (horizon in (1, 3, 5, 10)),
  ic numeric,
  n integer not null default 0,
  computed_at timestamptz not null,
  primary key (snapshot_date, config_version, factor, horizon)
);
create index if not exists v4_ic_daily_version_idx
  on public.v4_ic_daily_snapshot(config_version, snapshot_date desc, factor, horizon);

create table if not exists public.v4_dashboard_version_summary (
  scoring_version text primary key,
  signal_date_min date,
  signal_date_max date,
  signal_days integer not null default 0,
  signal_rows bigint not null default 0,
  outcome_date_min date,
  outcome_date_max date,
  outcome_rows bigint not null default 0,
  latest_update timestamptz,
  refreshed_at timestamptz not null default now()
);

alter table public.v4_analysis_diagnostics_snapshot enable row level security;
alter table public.v4_ic_daily_snapshot enable row level security;
alter table public.v4_dashboard_version_summary enable row level security;

drop policy if exists "read analysis diagnostics snapshot" on public.v4_analysis_diagnostics_snapshot;
create policy "read analysis diagnostics snapshot" on public.v4_analysis_diagnostics_snapshot
  for select to anon, authenticated using (true);
drop policy if exists "read ic daily snapshot" on public.v4_ic_daily_snapshot;
create policy "read ic daily snapshot" on public.v4_ic_daily_snapshot
  for select to anon, authenticated using (true);
drop policy if exists "read dashboard version summary" on public.v4_dashboard_version_summary;
create policy "read dashboard version summary" on public.v4_dashboard_version_summary
  for select to anon, authenticated using (true);

grant select on public.v4_analysis_diagnostics_snapshot, public.v4_ic_daily_snapshot,
  public.v4_dashboard_version_summary to anon, authenticated;
grant all on public.v4_analysis_diagnostics_snapshot, public.v4_ic_daily_snapshot,
  public.v4_dashboard_version_summary to service_role;

create or replace function public.refresh_v4_dashboard_snapshots()
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  refreshed timestamptz := clock_timestamp();
  diagnostics_count integer := 0;
  versions_count integer := 0;
begin
  delete from public.v4_analysis_diagnostics_snapshot;

  insert into public.v4_analysis_diagnostics_snapshot
    (scoring_version, kind, factor, grp, n, corr_ret5, corr_win, computed_at)
  select scoring_version, 'factor', factor, grp, n, corr_ret5, corr_win, refreshed
  from public.v4_hit_factor_corr;

  insert into public.v4_analysis_diagnostics_snapshot
    (scoring_version, kind, factor, factor_b, n, corr, computed_at)
  select scoring_version, 'pair', fa, fb, n, corr, refreshed
  from public.v4_factor_pair_corr;

  insert into public.v4_analysis_diagnostics_snapshot
    (scoring_version, kind, dim, bucket, factor, grp, n, corr_ret5, corr_win, computed_at)
  select scoring_version, 'split', dim, bucket, factor, grp, n, corr_ret5, corr_win, refreshed
  from public.v4_hit_factor_corr_split;

  get diagnostics diagnostics_count = row_count;

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
    'version_rows', versions_count,
    'ic_history_rows', (select count(*) from public.v4_ic_daily_snapshot)
  );
end;
$$;

revoke all on function public.refresh_v4_dashboard_snapshots() from public, anon, authenticated;
grant execute on function public.refresh_v4_dashboard_snapshots() to service_role;

commit;
