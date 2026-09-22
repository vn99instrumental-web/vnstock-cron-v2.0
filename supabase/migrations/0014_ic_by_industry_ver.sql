-- 0014_ic_by_industry_ver.sql — IC score_trade theo NGÀNH × VERSION × horizon.
--
-- Bổ sung chiều scoring_version cho IC-theo-ngành (view 0013 gộp mọi version).
-- Giữ nguyên v4_ic_by_industry (pooled) cho badge /buy; view này cho tab IC hiển
-- thị per-version. Spearman rank-IC gộp trong từng version. Ước lượng tham chiếu.

create or replace view public.v4_ic_by_industry_ver as
with base as (
  select s.scoring_version as version,
         s.breakdown->>'industry' as industry, h.horizon,
         (s.breakdown->>'score_trade')::numeric as val,
         case h.horizon when 1 then o.ret_1d when 3 then o.ret_3d
                        when 5 then o.ret_5d else o.ret_10d end as ret
  from public.v4_signals s
  join public.v4_outcomes o
    on o.symbol = s.symbol and o.signal_date = s.signal_date
   and o.snap_time = to_char(s.snap_time at time zone 'Asia/Ho_Chi_Minh', 'HH24:MI')
   and o.lens = 'trade'
  cross join (values (1),(3),(5),(10)) h(horizon)
  where s.breakdown->>'industry' is not null
    and s.scoring_version is not null
    and (s.breakdown->>'score_trade') ~ '^-?[0-9.]+$'
),
r as (
  select version, industry, horizon,
         rank() over (partition by version, industry, horizon order by val) rv,
         rank() over (partition by version, industry, horizon order by ret) rr
  from base where ret is not null
)
select version, industry, horizon, round(corr(rv, rr)::numeric, 3) as ic, count(*)::int as n
from r group by version, industry, horizon;

grant select on public.v4_ic_by_industry_ver to anon, authenticated;
