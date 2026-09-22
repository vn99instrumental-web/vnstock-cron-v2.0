-- 0015_ic_by_factor_ver.sql — IC theo NHÂN TỐ × VERSION × horizon (mọi version).
--
-- Mục tiêu: soi factor nào dự báo tốt ở TỪNG version → combine yếu tố tích cực
-- để thiết kế version mới. Phủ HẾT mọi version có trong signals (kể cả version cũ
-- chỉ 1–2 ngày mà evaluator chính thức không đủ chuẩn ≥3 ngày để chấm).
--
-- ƯỚC LƯỢNG tham chiếu (KHÁC v4_ic_metrics chính thức):
--   • Spearman rank-IC GỘP toàn kỳ trong từng version (rank(norm) vs rank(ret)),
--     KHÔNG tách theo ngày rồi trung bình như evaluator Python.
--   • Dùng đúng bộ cột nhân tố evaluator dùng: score_trade + trade_<factor>_norm.
--   • Join v4_signals.breakdown ↔ v4_outcomes qua (symbol, signal_date, snap giờ VN,
--     lens=trade). Version cũ n nhỏ ⇒ nhiễu cao, chỉ tham chiếu.
-- Read-only; cấp SELECT cho anon/authenticated.

create or replace view public.v4_ic_by_factor_ver as
with base as (
  select s.scoring_version as version, f.factor, h.horizon,
         (s.breakdown->>f.col)::numeric as val,
         case h.horizon when 1 then o.ret_1d when 3 then o.ret_3d
                        when 5 then o.ret_5d else o.ret_10d end as ret
  from public.v4_signals s
  join public.v4_outcomes o
    on o.symbol = s.symbol and o.signal_date = s.signal_date
   and o.snap_time = to_char(s.snap_time at time zone 'Asia/Ho_Chi_Minh', 'HH24:MI')
   and o.lens = 'trade'
  cross join lateral (values
    ('score_trade',    'score_trade'),
    ('mean_reversion', 'trade_mean_reversion_norm'),
    ('breakout',       'trade_breakout_norm'),
    ('flow',           'trade_flow_norm'),
    ('fundamental',    'trade_fundamental_norm'),
    ('growth',         'trade_growth_norm'),
    ('context',        'trade_context_norm')) f(factor, col)
  cross join (values (1),(3),(5),(10)) h(horizon)
  where s.scoring_version is not null
    and (s.breakdown->>f.col) ~ '^-?[0-9.]+$'
),
r as (
  select version, factor, horizon,
         rank() over (partition by version, factor, horizon order by val) rv,
         rank() over (partition by version, factor, horizon order by ret) rr
  from base where ret is not null
)
select version, factor, horizon, round(corr(rv, rr)::numeric, 3) as ic, count(*)::int as n
from r group by version, factor, horizon;

grant select on public.v4_ic_by_factor_ver to anon, authenticated;
