-- 0019_ic_by_industry_factor_ver.sql — IC theo VERSION × NHÂN TỐ × NGÀNH × horizon.
--
-- Ước lượng Spearman pooled để so tương đối các nhóm scoring trong từng ngành.
-- Bảng official v4_ic_metrics vẫn là nguồn IC chính thức theo ngày.
-- security_invoker giữ RLS của v4_signals/v4_outcomes; view chỉ cấp quyền đọc.

create or replace view public.v4_ic_by_industry_factor_ver
with (security_invoker = true)
as
with base as (
  select
    s.scoring_version as version,
    f.factor,
    s.breakdown->>'industry' as industry,
    h.horizon,
    (s.breakdown->>f.col)::numeric as val,
    case h.horizon
      when 1 then o.ret_1d
      when 3 then o.ret_3d
      when 5 then o.ret_5d
      else o.ret_10d
    end as ret
  from public.v4_signals s
  join public.v4_outcomes o
    on o.symbol = s.symbol
   and o.signal_date = s.signal_date
   and o.snap_time = to_char(s.snap_time at time zone 'Asia/Ho_Chi_Minh', 'HH24:MI')
   and o.lens = 'trade'
  cross join lateral (values
    ('score_trade',    'score_trade'),
    ('mean_reversion', 'trade_mean_reversion_norm'),
    ('breakout',       'trade_breakout_norm'),
    ('flow',           'trade_flow_norm'),
    ('fundamental',    'trade_fundamental_norm'),
    ('growth',         'trade_growth_norm'),
    ('context',        'trade_context_norm')
  ) f(factor, col)
  cross join (values (1), (3), (5), (10)) h(horizon)
  where s.scoring_version is not null
    and s.breakdown->>'industry' is not null
    and (s.breakdown->>f.col) ~ '^-?[0-9]+([.][0-9]+)?$'
), ranked as (
  select
    version,
    factor,
    industry,
    horizon,
    rank() over (partition by version, factor, industry, horizon order by val) as value_rank,
    rank() over (partition by version, factor, industry, horizon order by ret) as return_rank
  from base
  where ret is not null
)
select
  version,
  factor,
  industry,
  horizon,
  round(corr(value_rank::double precision, return_rank::double precision)::numeric, 3) as ic,
  count(*)::int as n
from ranked
group by version, factor, industry, horizon;

revoke all on public.v4_ic_by_industry_factor_ver from anon, authenticated;
grant select on public.v4_ic_by_industry_factor_ver to anon, authenticated;