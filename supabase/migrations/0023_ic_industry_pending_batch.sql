alter table public.v4_ic_industry_batch
  drop constraint if exists v4_ic_industry_batch_status_check;
alter table public.v4_ic_industry_batch
  add constraint v4_ic_industry_batch_status_check
  check (status in ('pending', 'ready'));
