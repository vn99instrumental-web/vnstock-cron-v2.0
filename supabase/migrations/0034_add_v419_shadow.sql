-- Register v4.19-shadow in version-safe analytics and bounded serving retention.
-- No table is added; existing RLS boundaries remain in force through security_invoker.

begin;

create or replace view public.v4_signal_analysis_feed
with (security_invoker = true)
as
with ranked_buy as (
  select
    s.breakdown->>'pred_id' as pred_id,
    s.scoring_version,
    s.symbol,
    s.signal_date,
    to_char(s.snap_time at time zone 'Asia/Ho_Chi_Minh', 'HH24:MI') as snap_time,
    s.decision,
    s.breakdown->>'confidence' as signal_confidence,
    case when s.breakdown->>'price' ~ '^-?[0-9]+([.][0-9]+)?$'
      then (s.breakdown->>'price')::numeric end as signal_price,
    s.entry as own_entry,
    s.tp1 as own_tp1,
    case when s.breakdown->>'tp2' ~ '^-?[0-9]+([.][0-9]+)?$'
      then (s.breakdown->>'tp2')::numeric end as own_tp2,
    s.stop as own_stop,
    row_number() over (
      partition by s.scoring_version, s.symbol, s.signal_date
      order by s.snap_time desc, s.id desc
    ) as rn
  from public.v4_signals s
  where s.scoring_version in ('v4.19-shadow', 'v4.18', 'v4.17', 'v4.9', 'v4.8', 'v4.1', 'v2.3')
    and s.decision in ('BUY', 'STRONG BUY')
),
latest_buy as (
  select * from ranked_buy where rn = 1
),
base as (
  select
    s.*,
    o.pred_id as outcome_pred_id,
    o.confidence as outcome_confidence,
    o.t0_close,
    o.ret_1d,
    o.ret_3d,
    o.ret_5d,
    o.ret_10d,
    o.mfe_pct,
    o.mae_pct
  from latest_buy s
  left join public.v4_outcomes o
    on o.pred_id = s.pred_id
   and o.scoring_version = s.scoring_version
   and o.lens = 'trade'
   and o.mfe_pct is not null
   and o.t0_close is not null
),
hits as (
  select b.*, h.*
  from base b
  left join lateral (
    select
      (array_agg(x.close order by x.date))[3] as close_3,
      (array_agg(x.close order by x.date))[5] as close_5,
      min(x.date) filter (where x.high >= b.t0_close * 1.06) as d_up6,
      min(x.date) filter (where x.low  <= b.t0_close * 0.96) as d_dn4,
      min(x.date) filter (where x.high >= b.t0_close * 1.03) as d_up3,
      min(x.date) filter (where x.low  <= b.t0_close * 0.97) as d_dn3,
      min(x.date) filter (where b.own_tp1 is not null and x.high >= b.own_tp1) as d_otp1,
      min(x.date) filter (where b.own_tp2 is not null and x.high >= b.own_tp2) as d_otp2,
      min(x.date) filter (where b.own_stop is not null and x.low <= b.own_stop) as d_ostop
    from public.v4_ohlc x
    where x.symbol = b.symbol
      and x.date > b.signal_date
      and x.date <= b.signal_date + 16
  ) h on true
)
select
  pred_id,
  scoring_version,
  symbol,
  signal_date,
  snap_time,
  decision,
  coalesce(outcome_confidence, signal_confidence) as confidence,
  coalesce(t0_close, signal_price) as t0_close,
  ret_1d,
  coalesce(ret_3d, case when close_3 is not null then (close_3 - coalesce(t0_close, signal_price)) / nullif(coalesce(t0_close, signal_price), 0) * 100 end) as ret_3d,
  coalesce(ret_5d, case when close_5 is not null then (close_5 - coalesce(t0_close, signal_price)) / nullif(coalesce(t0_close, signal_price), 0) * 100 end) as ret_5d,
  ret_10d,
  mfe_pct,
  mae_pct,
  own_entry,
  own_tp1,
  own_tp2,
  own_stop,
  case
    when outcome_pred_id is null then null
    when d_up6 is not null and (d_dn4 is null or d_up6 < d_dn4) then 'tp'
    when d_dn4 is not null and (d_up6 is null or d_dn4 <= d_up6) then 'sl'
    else 'open'
  end as std_outcome,
  case
    when outcome_pred_id is null then null
    when d_up6 is not null and (d_dn4 is null or d_up6 < d_dn4) then d_up6 - signal_date
    when d_dn4 is not null and (d_up6 is null or d_dn4 <= d_up6) then d_dn4 - signal_date
    else null
  end as std_days,
  case
    when outcome_pred_id is null then null
    when d_up3 is not null and (d_dn3 is null or d_up3 < d_dn3) then 'tp'
    when d_dn3 is not null and (d_up3 is null or d_dn3 <= d_up3) then 'sl'
    else 'open'
  end as std3_outcome,
  case
    when outcome_pred_id is null then null
    when own_tp1 is null and own_stop is null then null
    when d_otp2 is not null and (d_ostop is null or d_otp2 < d_ostop) then 'tp2'
    when d_otp1 is not null and (d_ostop is null or d_otp1 < d_ostop) then 'tp1'
    when d_ostop is not null then 'sl'
    else 'open'
  end as own_outcome,
  case
    when outcome_pred_id is null then null
    when own_tp1 is null and own_stop is null then null
    when d_otp1 is not null and (d_ostop is null or d_otp1 < d_ostop) then d_otp1 - signal_date
    when d_ostop is not null then d_ostop - signal_date
    else null
  end as own_days
from hits;

revoke all on public.v4_signal_analysis_feed from anon, authenticated;
grant select on public.v4_signal_analysis_feed to anon, authenticated;

-- Bound Supabase serving storage while keeping the Git ledger lossless.
-- Full intraday: v4.18/v4.17. The shadow and older review versions retain the final run and
-- final BUY-bearing run of every day so Buy keeps its complete drill-down.

create or replace function public.prune_v4_legacy_intraday()
returns jsonb language plpgsql security invoker set search_path = pg_catalog, public
as $$
declare
  signal_rows_before bigint; signal_rows_after bigint;
  outcome_rows_before bigint; outcome_rows_after bigint;
  run_rows_before bigint; run_rows_after bigint;
begin
  select count(*) into signal_rows_before from public.v4_signals where scoring_version = any (array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3']);
  select count(*) into outcome_rows_before from public.v4_outcomes where scoring_version = any (array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3']);
  select count(*) into run_rows_before from public.v4_runs where scoring_version = any (array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3']);

  create temporary table keep_v4_legacy_runs (run_id text primary key) on commit drop;
  insert into keep_v4_legacy_runs (run_id)
  select run_id from (
    select distinct on (scoring_version, signal_date) scoring_version, signal_date, run_id
    from public.v4_signals
    where scoring_version = any (array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3']) and run_id is not null
    order by scoring_version, signal_date, snap_time desc, id desc
  ) daily_close;
  insert into keep_v4_legacy_runs (run_id)
  select run_id from (
    select distinct on (scoring_version, signal_date) scoring_version, signal_date, run_id
    from public.v4_signals
    where scoring_version = any (array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3'])
      and decision in ('BUY','STRONG BUY') and run_id is not null
    order by scoring_version, signal_date, snap_time desc, id desc
  ) daily_buy on conflict (run_id) do nothing;

  delete from public.v4_signals signal
  where signal.scoring_version = any (array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3'])
    and not exists (select 1 from keep_v4_legacy_runs kept where kept.run_id = signal.run_id);
  delete from public.v4_outcomes outcome
  where outcome.scoring_version = any (array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3'])
    and not exists (
      select 1 from public.v4_signals signal
      where signal.scoring_version = outcome.scoring_version and signal.breakdown->>'pred_id' = outcome.pred_id
    );
  delete from public.v4_runs run
  where run.scoring_version = any (array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3'])
    and not exists (select 1 from public.v4_signals signal where signal.run_id = run.run_id);

  select count(*) into signal_rows_after from public.v4_signals where scoring_version = any (array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3']);
  select count(*) into outcome_rows_after from public.v4_outcomes where scoring_version = any (array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3']);
  select count(*) into run_rows_after from public.v4_runs where scoring_version = any (array['v4.19-shadow','v4.9','v4.8','v4.1','v2.3']);
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
  'Retains full intraday for v4.18/v4.17 and daily close plus latest BUY run for v4.19-shadow and older review versions.';

commit;
