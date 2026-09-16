-- 0010_corr_heatmap_and_split.sql — E8++: (a) ma trận tương quan biến×biến (bắt đa cộng
-- tuyến/biến trùng), (b) tương quan biến↔kết quả TÁCH theo confidence & regime.
-- Vẫn KHÁM PHÁ, không phải IC chính thức. Grant anon SELECT (chỉ aggregate data public).

-- (a) Ma trận tương quan giữa các biến (chỉ nửa trên fa<fb; UI tự soi gương + đường chéo=1).
create or replace view public.v4_factor_pair_corr as
with u as (
  select r.pred_id, kv.key as factor, kv.value::numeric as val
  from public.v4_signal_results r
  join public.v4_signals s on s.breakdown->>'pred_id' = r.pred_id,
       lateral jsonb_each_text(s.breakdown) kv
  where kv.value ~ '^-?[0-9]+\.?[0-9]*$'
    and kv.key in (select factor from public.v4_hit_factor_corr)
)
select a.factor as fa, b.factor as fb,
       round(corr(a.val, b.val)::numeric, 3) as corr,
       count(*) as n
from u a
join u b on a.pred_id = b.pred_id and a.factor < b.factor
group by a.factor, b.factor
having count(*) >= 50 and corr(a.val, b.val) is not null;

grant select on public.v4_factor_pair_corr to anon, authenticated;

-- (b) Tương quan biến↔kết quả tách theo confidence & regime.
create or replace view public.v4_hit_factor_corr_split as
with base as (
  select r.ret_5d, (r.std_outcome = 'tp')::int as win,
         r.confidence, s.breakdown->>'regime' as regime, s.breakdown
  from public.v4_signal_results r
  join public.v4_signals s on s.breakdown->>'pred_id' = r.pred_id
),
long as (
  select ret_5d, win, confidence, regime, kv.key as factor, kv.value::numeric as val
  from base, lateral jsonb_each_text(breakdown) kv
  where kv.value ~ '^-?[0-9]+\.?[0-9]*$'
    and kv.key !~ '^_'
    and kv.key not like 'score\_trade\_%'
    and kv.key not in ('price','score_trade','gate_version','registry_version','schema_version',
                       'scoring_version','result_5d','result_30d','pred_id','entry','tp1','tp2','stop')
),
by_conf as (
  select 'confidence' as dim, confidence as bucket, factor,
         count(*) as n,
         round(corr(ret_5d, val)::numeric, 3) as corr_ret5,
         round(corr(win, val)::numeric, 3) as corr_win
  from long where confidence is not null
  group by confidence, factor
),
by_regime as (
  select 'regime' as dim, regime as bucket, factor,
         count(*) as n,
         round(corr(ret_5d, val)::numeric, 3) as corr_ret5,
         round(corr(win, val)::numeric, 3) as corr_win
  from long where regime is not null
  group by regime, factor
)
select dim, bucket, factor, n, corr_ret5, corr_win,
  case
    when factor like 's\_%'              then 'signal'
    when factor like 'trade\_%\_norm'    then 'factor_trade'
    when factor like 'hold\_%\_norm'     then 'factor_hold'
    when factor like 'rank\_%'           then 'rank'
    when factor like 'ff\_intra\_%' or factor = 'of_bp_pts' then 'flow'
    else 'other'
  end as grp
from (select * from by_conf union all select * from by_regime) t
where n >= 25 and corr_ret5 is not null;

grant select on public.v4_hit_factor_corr_split to anon, authenticated;
