-- 0009_hit_factor_corr_allvars.sql — mở rộng tương quan ra TẤT CẢ biến số trong breakdown
-- (không chỉ s_*). Vẫn là KHÁM PHÁ, không phải IC chính thức (Golden rule #3).
-- LOẠI: biến rò rỉ kết quả (result_5d/30d), ID/version (*_version, schema/registry, pred_id),
--       score shadow/what-if (_*delta, score_trade_*), mức giá & ngưỡng (price, entry/tp/stop).
-- Thêm cột grp để UI nhóm: signal / factor_trade / factor_hold / rank / flow / other.

create or replace view public.v4_hit_factor_corr as
with j as (
  select r.ret_5d, (r.std_outcome = 'tp')::int as win, s.breakdown
  from public.v4_signal_results r
  join public.v4_signals s on s.breakdown->>'pred_id' = r.pred_id
),
unp as (
  select kv.key as factor, kv.value as val, j.ret_5d, j.win
  from j, lateral jsonb_each_text(j.breakdown) kv
  where kv.value ~ '^-?[0-9]+\.?[0-9]*$'
    and kv.key !~ '^_'
    and kv.key not like 'score\_trade\_%'
    and kv.key not in ('price','score_trade','gate_version','registry_version','schema_version',
                       'scoring_version','result_5d','result_30d','pred_id','entry','tp1','tp2','stop')
),
agg as (
  select factor,
         count(*) as n,
         round(corr(ret_5d, val::numeric)::numeric, 3) as corr_ret5,
         round(corr(win,    val::numeric)::numeric, 3) as corr_win
  from unp
  group by factor
  having count(*) >= 100 and corr(ret_5d, val::numeric) is not null
)
select
  factor, n, corr_ret5, corr_win,
  case
    when factor like 's\_%'              then 'signal'
    when factor like 'trade\_%\_norm'    then 'factor_trade'
    when factor like 'hold\_%\_norm'     then 'factor_hold'
    when factor like 'rank\_%'           then 'rank'
    when factor like 'ff\_intra\_%' or factor = 'of_bp_pts' then 'flow'
    else 'other'
  end as grp
from agg
order by abs(corr_ret5) desc nulls last;

grant select on public.v4_hit_factor_corr to anon, authenticated;
