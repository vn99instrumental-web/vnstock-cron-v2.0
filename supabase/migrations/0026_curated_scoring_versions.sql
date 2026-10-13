-- Curated cross-version review: v4.18, v4.17, v4.9, v4.8, v4.1 and legacy v2.3.
-- Every analysis join and aggregation is version-safe.

begin;

drop view if exists public.v4_factor_pair_corr;
drop view if exists public.v4_hit_factor_corr_split;
drop view if exists public.v4_hit_factor_corr;
drop view if exists public.v4_signal_analysis_feed;

create view public.v4_signal_analysis_feed
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
  where s.scoring_version in ('v4.18', 'v4.17', 'v4.9', 'v4.8', 'v4.1', 'v2.3')
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

create view public.v4_hit_factor_corr
with (security_invoker = true)
as
with j as (
  select r.scoring_version, r.ret_5d, (r.std_outcome = 'tp')::int as win, s.breakdown
  from public.v4_signal_analysis_feed r
  join public.v4_signals s
    on s.breakdown->>'pred_id' = r.pred_id
   and s.scoring_version = r.scoring_version
  where r.ret_5d is not null
),
unp as (
  select scoring_version, kv.key as factor, kv.value as val, ret_5d, win
  from j, lateral jsonb_each_text(j.breakdown) kv
  where kv.value ~ '^-?[0-9]+([.][0-9]+)?$'
    and kv.key !~ '^_'
    and kv.key not like 'score\_trade\_%'
    and kv.key not in ('price','score_trade','total_score','gate_version','registry_version','schema_version',
                       'scoring_version','result_5d','result_30d','pred_id','entry','tp1','tp2','stop','stop_loss')
),
agg as (
  select scoring_version, factor, count(*) as n,
         round(corr(ret_5d, val::numeric)::numeric, 3) as corr_ret5,
         round(corr(win, val::numeric)::numeric, 3) as corr_win
  from unp
  group by scoring_version, factor
  having count(*) >= 30 and corr(ret_5d, val::numeric) is not null
)
select scoring_version, factor, n, corr_ret5, corr_win,
  case
    when factor like 's\_%' then 'signal'
    when factor like 'trade\_%\_norm' then 'factor_trade'
    when factor like 'hold\_%\_norm' then 'factor_hold'
    when factor like 'rank\_%' then 'rank'
    when factor like 'ff\_intra\_%' or factor = 'of_bp_pts' then 'flow'
    else 'other'
  end as grp
from agg;

create view public.v4_factor_pair_corr
with (security_invoker = true)
as
with u as (
  select r.scoring_version, r.pred_id, kv.key as factor, kv.value::numeric as val
  from public.v4_signal_analysis_feed r
  join public.v4_signals s
    on s.breakdown->>'pred_id' = r.pred_id
   and s.scoring_version = r.scoring_version,
       lateral jsonb_each_text(s.breakdown) kv
  where r.ret_5d is not null
    and kv.value ~ '^-?[0-9]+([.][0-9]+)?$'
    and exists (
      select 1 from public.v4_hit_factor_corr f
      where f.scoring_version = r.scoring_version and f.factor = kv.key
    )
)
select a.scoring_version, a.factor as fa, b.factor as fb,
       round(corr(a.val, b.val)::numeric, 3) as corr,
       count(*) as n
from u a
join u b
  on b.scoring_version = a.scoring_version
 and b.pred_id = a.pred_id
 and a.factor < b.factor
group by a.scoring_version, a.factor, b.factor
having count(*) >= 30 and corr(a.val, b.val) is not null;

create view public.v4_hit_factor_corr_split
with (security_invoker = true)
as
with base as (
  select r.scoring_version, r.ret_5d, (r.std_outcome = 'tp')::int as win,
         r.confidence, s.breakdown->>'regime' as regime, s.breakdown
  from public.v4_signal_analysis_feed r
  join public.v4_signals s
    on s.breakdown->>'pred_id' = r.pred_id
   and s.scoring_version = r.scoring_version
  where r.ret_5d is not null
),
long as (
  select scoring_version, ret_5d, win, confidence, regime,
         kv.key as factor, kv.value::numeric as val
  from base, lateral jsonb_each_text(breakdown) kv
  where kv.value ~ '^-?[0-9]+([.][0-9]+)?$'
    and kv.key !~ '^_'
    and kv.key not like 'score\_trade\_%'
    and kv.key not in ('price','score_trade','total_score','gate_version','registry_version','schema_version',
                       'scoring_version','result_5d','result_30d','pred_id','entry','tp1','tp2','stop','stop_loss')
),
by_conf as (
  select scoring_version, 'confidence'::text as dim, confidence as bucket, factor,
         count(*) as n, round(corr(ret_5d, val)::numeric, 3) as corr_ret5,
         round(corr(win, val)::numeric, 3) as corr_win
  from long where confidence is not null
  group by scoring_version, confidence, factor
),
by_regime as (
  select scoring_version, 'regime'::text as dim, regime as bucket, factor,
         count(*) as n, round(corr(ret_5d, val)::numeric, 3) as corr_ret5,
         round(corr(win, val)::numeric, 3) as corr_win
  from long where regime is not null
  group by scoring_version, regime, factor
)
select scoring_version, dim, bucket, factor, n, corr_ret5, corr_win,
  case
    when factor like 's\_%' then 'signal'
    when factor like 'trade\_%\_norm' then 'factor_trade'
    when factor like 'hold\_%\_norm' then 'factor_hold'
    when factor like 'rank\_%' then 'rank'
    when factor like 'ff\_intra\_%' or factor = 'of_bp_pts' then 'flow'
    else 'other'
  end as grp
from (select * from by_conf union all select * from by_regime) t
where n >= 20 and corr_ret5 is not null;

revoke all on public.v4_signal_analysis_feed, public.v4_hit_factor_corr,
  public.v4_factor_pair_corr, public.v4_hit_factor_corr_split from anon, authenticated;
grant select on public.v4_signal_analysis_feed, public.v4_hit_factor_corr,
  public.v4_factor_pair_corr, public.v4_hit_factor_corr_split to anon, authenticated;

commit;
