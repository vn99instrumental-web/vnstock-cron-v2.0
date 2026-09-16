-- 0008_signal_results_views.sql — E8: theo dõi TP/SL & tương quan biến đầu vào.
-- Chỉ TỔNG HỢP từ v4_outcomes + v4_signals + v4_ohlc (data vốn public) → grant anon SELECT.
-- KHÔNG reimplement scoring/IC "chính thức" (đó là Python). Đây là lớp KHÁM PHÁ có dán nhãn.
--
-- Phương pháp "hit": đi theo NẾN THẬT v4_ohlc từ ngày sau tín hiệu, cửa sổ ~10 phiên (+16 ngày
-- lịch). Xác định TP hay SL chạm TRƯỚC theo NGÀY. Quy ước bảo thủ: nếu 1 nến vừa chạm TP vừa
-- chạm SL (không biết thứ tự trong ngày) → tính SL trước.
--   • std = mục tiêu CHUẨN hoá (không phụ thuộc TP model): +6%/−4% và +3%/−3% so với t0_close.
--   • own = TP/SL RIÊNG model đặt lúc ra tín hiệu (breakdown entry/tp1/tp2/stop) — chỉ có từ T9/2026.

create or replace view public.v4_signal_results as
with sig as (
  select o.pred_id, o.symbol, o.signal_date, o.snap_time, o.decision, o.confidence,
         o.t0_close, o.ret_5d, o.ret_1d, o.ret_10d, o.mfe_pct, o.mae_pct, o.n_bars,
         (b.breakdown->>'entry')::numeric as own_entry,
         (b.breakdown->>'tp1')::numeric   as own_tp1,
         (b.breakdown->>'tp2')::numeric   as own_tp2,
         (b.breakdown->>'stop')::numeric  as own_stop
  from public.v4_outcomes o
  join public.v4_signals b on b.breakdown->>'pred_id' = o.pred_id
  where o.decision in ('BUY','STRONG BUY') and o.lens = 'trade'
    and o.mfe_pct is not null and o.t0_close is not null
),
w as (
  select s.*,
    (select min(date) from public.v4_ohlc o where o.symbol=s.symbol and o.date>s.signal_date and o.date<=s.signal_date+16 and o.high>=s.t0_close*1.06) as d_up6,
    (select min(date) from public.v4_ohlc o where o.symbol=s.symbol and o.date>s.signal_date and o.date<=s.signal_date+16 and o.low <=s.t0_close*0.96) as d_dn4,
    (select min(date) from public.v4_ohlc o where o.symbol=s.symbol and o.date>s.signal_date and o.date<=s.signal_date+16 and o.high>=s.t0_close*1.03) as d_up3,
    (select min(date) from public.v4_ohlc o where o.symbol=s.symbol and o.date>s.signal_date and o.date<=s.signal_date+16 and o.low <=s.t0_close*0.97) as d_dn3,
    (select min(date) from public.v4_ohlc o where o.symbol=s.symbol and o.date>s.signal_date and o.date<=s.signal_date+16 and s.own_tp1 is not null and o.high>=s.own_tp1)  as d_otp1,
    (select min(date) from public.v4_ohlc o where o.symbol=s.symbol and o.date>s.signal_date and o.date<=s.signal_date+16 and s.own_tp2 is not null and o.high>=s.own_tp2)  as d_otp2,
    (select min(date) from public.v4_ohlc o where o.symbol=s.symbol and o.date>s.signal_date and o.date<=s.signal_date+16 and s.own_stop is not null and o.low<=s.own_stop) as d_ostop
  from sig s
)
select
  pred_id, symbol, signal_date, snap_time, decision, confidence,
  t0_close, ret_1d, ret_5d, ret_10d, mfe_pct, mae_pct, n_bars,
  own_entry, own_tp1, own_tp2, own_stop,
  -- std +6% / −4%
  case when d_up6 is not null and (d_dn4 is null or d_up6 <  d_dn4) then 'tp'
       when d_dn4 is not null and (d_up6 is null or d_dn4 <= d_up6) then 'sl'
       else 'open' end as std_outcome,
  case when d_up6 is not null and (d_dn4 is null or d_up6 <  d_dn4) then (d_up6 - signal_date)
       when d_dn4 is not null and (d_up6 is null or d_dn4 <= d_up6) then (d_dn4 - signal_date)
       else null end as std_days,
  -- std +3% / −3% (mục tiêu mềm hơn)
  case when d_up3 is not null and (d_dn3 is null or d_up3 <  d_dn3) then 'tp'
       when d_dn3 is not null and (d_up3 is null or d_dn3 <= d_up3) then 'sl'
       else 'open' end as std3_outcome,
  -- own TP/SL model (null trước T9)
  case when own_tp1 is null and own_stop is null then null
       when d_otp2 is not null and (d_ostop is null or d_otp2 < d_ostop) then 'tp2'
       when d_otp1 is not null and (d_ostop is null or d_otp1 < d_ostop) then 'tp1'
       when d_ostop is not null then 'sl'
       else 'open' end as own_outcome,
  case when own_tp1 is null and own_stop is null then null
       when d_otp1 is not null and (d_ostop is null or d_otp1 < d_ostop) then (d_otp1 - signal_date)
       when d_ostop is not null then (d_ostop - signal_date)
       else null end as own_days
from w;

grant select on public.v4_signal_results to anon, authenticated;

-- Tương quan biến input (s_*) với kết quả — KHÁM PHÁ, không phải IC chính thức.
-- corr_ret5 = corr(giá trị biến, lợi nhuận 5 phiên); corr_win = corr(biến, chạm TP +6% trước).
create or replace view public.v4_hit_factor_corr as
with j as (
  select r.ret_5d, (r.std_outcome = 'tp')::int as win, s.breakdown
  from public.v4_signal_results r
  join public.v4_signals s on s.breakdown->>'pred_id' = r.pred_id
),
unp as (
  select kv.key as factor, kv.value as val, j.ret_5d, j.win
  from j, lateral jsonb_each_text(j.breakdown) kv
  where kv.key like 's\_%' and kv.value ~ '^-?[0-9.]+$'
)
select
  factor,
  count(*) as n,
  round(corr(ret_5d, val::numeric)::numeric, 3) as corr_ret5,
  round(corr(win,    val::numeric)::numeric, 3) as corr_win
from unp
group by factor
having count(*) >= 30
order by abs(corr(ret_5d, val::numeric)) desc nulls last;

grant select on public.v4_hit_factor_corr to anon, authenticated;
