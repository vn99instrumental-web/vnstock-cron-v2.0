-- 0007_buy_robustness_view.sql — độ vững tín hiệu BUY cho app /buy (mục D/E/F).
-- Chỉ TỔNG HỢP từ v4_signals (dữ liệu vốn public) → không đụng scoring, grant anon SELECT.
--   E — buy_days_15d/total_days_15d : số phiên (ngày) mã giữ BUY trong ~15 phiên gần nhất.
--   F — buy_snaps_today/total_snaps_today + first_buy_snap_vn : đồng thuận trong ngày ra tín hiệu.
-- (D — thanh khoản ADTV — đọc thẳng breakdown->>'adtv_bil' ở app, không cần view.)

create or replace view public.v4_buy_robustness as
with latest_buy as (
  select run_id, signal_date
  from public.v4_signals
  where decision in ('BUY', 'STRONG BUY')
  order by signal_date desc, snap_time desc
  limit 1
),
d as (select signal_date as d0 from latest_buy),
total_days as (
  select count(distinct signal_date) as n
  from public.v4_signals
  where signal_date > (select d0 from d) - 21
    and signal_date <= (select d0 from d)
),
total_snaps as (
  select count(distinct snap_time) as n
  from public.v4_signals
  where signal_date = (select d0 from d)
),
buys as (
  select distinct symbol
  from public.v4_signals
  where run_id = (select run_id from latest_buy)
    and decision in ('BUY', 'STRONG BUY')
)
select
  b.symbol,
  (select d0 from d)                         as signal_date,
  (select n from total_days)                 as total_days_15d,
  (select n from total_snaps)                as total_snaps_today,
  coalesce((
    select count(distinct s.signal_date)
    from public.v4_signals s
    where s.symbol = b.symbol
      and s.decision in ('BUY', 'STRONG BUY')
      and s.signal_date > (select d0 from d) - 21
      and s.signal_date <= (select d0 from d)
  ), 0)                                       as buy_days_15d,
  coalesce((
    select count(*)
    from public.v4_signals s
    where s.symbol = b.symbol
      and s.signal_date = (select d0 from d)
      and s.decision in ('BUY', 'STRONG BUY')
  ), 0)                                       as buy_snaps_today,
  (
    select to_char(min(s.snap_time) at time zone 'Asia/Ho_Chi_Minh', 'HH24:MI')
    from public.v4_signals s
    where s.symbol = b.symbol
      and s.signal_date = (select d0 from d)
      and s.decision in ('BUY', 'STRONG BUY')
  )                                           as first_buy_snap_vn
from buys b;

grant select on public.v4_buy_robustness to anon, authenticated;
