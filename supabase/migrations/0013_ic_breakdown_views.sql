-- 0013_ic_breakdown_views.sql — IC breakdown: theo CHỈ SỐ CON và theo NGÀNH.
--
-- ƯỚC LƯỢNG tham khảo (KHÔNG phải IC chính thức của evaluator Python):
--   • Spearman rank-IC GỘP toàn kỳ (rank(val) vs rank(ret)), KHÔNG tách theo ngày
--     rồi trung bình như evaluator. Dùng để soi tương đối chỉ số/ngành nào dự báo tốt.
--   • Join v4_signals.breakdown ↔ v4_outcomes qua (symbol, signal_date, snap giờ VN, lens=trade).
--   • Gộp MỌI version — không tách theo scoring_version (khác v4_ic_metrics).
-- Đọc-only; cấp SELECT cho anon/authenticated (khớp pattern view khác).

-- ── IC theo CHỈ SỐ CON (s_*) × horizon ──────────────────────────────────────
create or replace view public.v4_ic_by_indicator as
with base as (
  select ind.k as indicator, h.horizon,
         (s.breakdown->>ind.k)::numeric as val,
         case h.horizon when 1 then o.ret_1d when 3 then o.ret_3d
                        when 5 then o.ret_5d else o.ret_10d end as ret
  from public.v4_signals s
  join public.v4_outcomes o
    on o.symbol = s.symbol and o.signal_date = s.signal_date
   and o.snap_time = to_char(s.snap_time at time zone 'Asia/Ho_Chi_Minh', 'HH24:MI')
   and o.lens = 'trade'
  cross join lateral (values
    ('s_willr_mr'),('s_bb_mr'),('s_overext_ema'),('s_rs_reversal'),('s_deep_dd'),
    ('s_dist_52w'),('s_vol_ratio_h'),('s_ff_net'),('s_of_phasefix'),('s_prop_5d'),
    ('s_insider'),('s_fund_core'),('s_growth_core'),('s_mkt_context'),('s_trend_st'),
    ('s_depth_wall'),('s_cf_core')) ind(k)
  cross join (values (1),(3),(5),(10)) h(horizon)
  where (s.breakdown->>ind.k) ~ '^-?[0-9.]+$'
),
r as (
  select indicator, horizon,
         rank() over (partition by indicator, horizon order by val) rv,
         rank() over (partition by indicator, horizon order by ret) rr
  from base where ret is not null
)
select indicator, horizon, round(corr(rv, rr)::numeric, 3) as ic, count(*)::int as n
from r group by indicator, horizon;

-- ── IC score_trade theo NGÀNH × horizon ─────────────────────────────────────
create or replace view public.v4_ic_by_industry as
with base as (
  select s.breakdown->>'industry' as industry, h.horizon,
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
    and (s.breakdown->>'score_trade') ~ '^-?[0-9.]+$'
),
r as (
  select industry, horizon,
         rank() over (partition by industry, horizon order by val) rv,
         rank() over (partition by industry, horizon order by ret) rr
  from base where ret is not null
)
select industry, horizon, round(corr(rv, rr)::numeric, 3) as ic, count(*)::int as n
from r group by industry, horizon;

grant select on public.v4_ic_by_indicator, public.v4_ic_by_industry to anon, authenticated;
