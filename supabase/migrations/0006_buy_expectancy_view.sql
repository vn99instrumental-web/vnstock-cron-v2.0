-- 0006_buy_expectancy_view.sql — view kỳ vọng BUY/STRONG BUY (win-rate, ret, MFE/MAE)
-- theo confidence, tổng hợp từ v4_outcomes (lens trade). App /buy đọc để hỗ trợ quyết định
-- mua ngắn hạn + gợi ý vùng chốt/cắt. Chỉ tổng hợp data vốn public → grant anon SELECT.

create or replace view public.v4_buy_expectancy as
select
  decision,
  coalesce(confidence, 'ALL') as confidence,
  count(*)                                   as n,
  round(avg(ret_1d)::numeric, 2)             as avg_ret_1d,
  round(avg(ret_5d)::numeric, 2)             as avg_ret_5d,
  round(avg(ret_10d)::numeric, 2)            as avg_ret_10d,
  round(avg(mfe_pct)::numeric, 2)            as avg_mfe,
  round(avg(mae_pct)::numeric, 2)            as avg_mae,
  round((100.0 * sum((ret_5d > 0)::int) / nullif(count(*), 0))::numeric, 1) as winrate_5d
from public.v4_outcomes
where lens = 'trade' and decision in ('BUY', 'STRONG BUY') and ret_5d is not null
group by decision, coalesce(confidence, 'ALL');

grant select on public.v4_buy_expectancy to anon, authenticated;
