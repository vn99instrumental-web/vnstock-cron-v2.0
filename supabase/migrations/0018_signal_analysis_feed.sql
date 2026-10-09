-- 0018_signal_analysis_feed.sql — unify the Analysis timeline with the Buy feed.
--
-- Buy reads v4_signals immediately, while v4_signal_results only contains
-- signals whose 10-session outcome is mature. This security-invoker feed keeps
-- one latest BUY snapshot per symbol/day, attaches an outcome when available,
-- and calculates all TP/SL hit dates in one OHLC scan per mature signal.
-- Pending signals stay visible with null outcome fields and are excluded from
-- win-rate denominators by the UI.

create or replace view public.v4_signal_analysis_feed
with (security_invoker = true)
as
with ranked_buy as (
  select
    s.breakdown->>'pred_id' as pred_id,
    s.symbol,
    s.signal_date,
    to_char(s.snap_time at time zone 'Asia/Ho_Chi_Minh', 'HH24:MI') as snap_time,
    s.decision,
    s.breakdown->>'confidence' as signal_confidence,
    case when s.breakdown->>'price' ~ '^-?[0-9]+(.[0-9]+)?$'
      then (s.breakdown->>'price')::numeric end as signal_price,
    s.entry as own_entry,
    s.tp1 as own_tp1,
    case when s.breakdown->>'tp2' ~ '^-?[0-9]+(.[0-9]+)?$'
      then (s.breakdown->>'tp2')::numeric end as own_tp2,
    s.stop as own_stop,
    row_number() over (
      partition by s.symbol, s.signal_date
      order by s.snap_time desc, s.id desc
    ) as rn
  from public.v4_signals s
  where s.decision in ('BUY', 'STRONG BUY')
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
    o.ret_5d,
    o.ret_10d,
    o.mfe_pct,
    o.mae_pct
  from latest_buy s
  left join public.v4_outcomes o
    on o.pred_id = s.pred_id
   and o.lens = 'trade'
   and o.mfe_pct is not null
   and o.t0_close is not null
),
hits as (
  select b.*, h.*
  from base b
  left join lateral (
    select
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
  ) h on b.outcome_pred_id is not null
)
select
  pred_id,
  symbol,
  signal_date,
  snap_time,
  decision,
  coalesce(outcome_confidence, signal_confidence) as confidence,
  coalesce(t0_close, signal_price) as t0_close,
  ret_1d,
  ret_5d,
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