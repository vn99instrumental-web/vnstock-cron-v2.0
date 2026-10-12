-- Keep Buy-tab supporting statistics aligned with the selected scoring version.
-- Existing column order is preserved; scoring_version is appended for backward compatibility.

create or replace view public.v4_buy_expectancy
with (security_invoker = true)
as
select
  decision,
  coalesce(confidence, 'ALL') as confidence,
  count(*) as n,
  round(avg(ret_1d), 2) as avg_ret_1d,
  round(avg(ret_5d), 2) as avg_ret_5d,
  round(avg(ret_10d), 2) as avg_ret_10d,
  round(avg(mfe_pct), 2) as avg_mfe,
  round(avg(mae_pct), 2) as avg_mae,
  round(
    100.0 * sum((ret_5d > 0)::integer)::numeric / nullif(count(*), 0)::numeric,
    1
  ) as winrate_5d,
  scoring_version
from public.v4_outcomes
where lens = 'trade'
  and decision in ('BUY', 'STRONG BUY')
  and ret_5d is not null
  and scoring_version is not null
group by scoring_version, decision, coalesce(confidence, 'ALL');

create or replace view public.v4_buy_robustness
with (security_invoker = true)
as
with latest_buy as (
  select distinct on (scoring_version)
    run_id,
    signal_date,
    scoring_version
  from public.v4_signals
  where decision in ('BUY', 'STRONG BUY')
    and scoring_version is not null
  order by scoring_version, signal_date desc, snap_time desc
),
total_days as (
  select
    lb.scoring_version,
    count(distinct s.signal_date) as n
  from latest_buy lb
  join public.v4_signals s
    on s.scoring_version = lb.scoring_version
   and s.signal_date > lb.signal_date - 21
   and s.signal_date <= lb.signal_date
  group by lb.scoring_version
),
total_snaps as (
  select
    lb.scoring_version,
    count(distinct s.snap_time) as n
  from latest_buy lb
  join public.v4_signals s
    on s.scoring_version = lb.scoring_version
   and s.signal_date = lb.signal_date
  group by lb.scoring_version
),
buys as (
  select distinct
    lb.scoring_version,
    lb.signal_date,
    s.symbol
  from latest_buy lb
  join public.v4_signals s
    on s.run_id = lb.run_id
   and s.scoring_version = lb.scoring_version
  where s.decision in ('BUY', 'STRONG BUY')
)
select
  b.symbol,
  b.signal_date,
  td.n as total_days_15d,
  ts.n as total_snaps_today,
  coalesce((
    select count(distinct s.signal_date)
    from public.v4_signals s
    where s.scoring_version = b.scoring_version
      and s.symbol = b.symbol
      and s.decision in ('BUY', 'STRONG BUY')
      and s.signal_date > b.signal_date - 21
      and s.signal_date <= b.signal_date
  ), 0::bigint) as buy_days_15d,
  coalesce((
    select count(*)
    from public.v4_signals s
    where s.scoring_version = b.scoring_version
      and s.symbol = b.symbol
      and s.signal_date = b.signal_date
      and s.decision in ('BUY', 'STRONG BUY')
  ), 0::bigint) as buy_snaps_today,
  (
    select to_char(min(s.snap_time) at time zone 'Asia/Ho_Chi_Minh', 'HH24:MI')
    from public.v4_signals s
    where s.scoring_version = b.scoring_version
      and s.symbol = b.symbol
      and s.signal_date = b.signal_date
      and s.decision in ('BUY', 'STRONG BUY')
  ) as first_buy_snap_vn,
  b.scoring_version
from buys b
join total_days td using (scoring_version)
join total_snaps ts using (scoring_version);

grant select on public.v4_buy_expectancy to anon, authenticated;
grant select on public.v4_buy_robustness to anon, authenticated;