-- 0005_ohlc.sql — bảng OHLC daily thật (backfill lịch sử) cho chart /buy (ADR-010 phương án B).
-- Nguồn: vnstock (VCI) qua scripts/export_ohlc_to_supabase.py chạy trên GH Actions.
-- App đọc v4_ohlc để vẽ nến daily thật (mỗi nến = 1 ngày), có lịch sử xa hơn ledger.
-- Grant tường minh (project đã thu hồi default): anon/auth SELECT, service_role ghi.

create table if not exists public.v4_ohlc (
  symbol     text not null,
  date       date not null,
  open       numeric,
  high       numeric,
  low        numeric,
  close      numeric,
  volume     numeric,
  synced_at  timestamptz not null default now(),
  primary key (symbol, date)
);
create index if not exists idx_v4_ohlc_symbol on public.v4_ohlc (symbol, date desc);

alter table public.v4_ohlc enable row level security;
create policy "read v4_ohlc" on public.v4_ohlc for select to anon, authenticated using (true);

grant select on public.v4_ohlc to anon, authenticated;
grant select, insert, update, delete on public.v4_ohlc to service_role;
