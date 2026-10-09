-- Persisted IC-by-industry snapshots.  The batch pointer prevents partial reads.
create table if not exists public.v4_ic_industry_batch (
  batch_id text primary key,
  computed_at timestamptz not null default now(),
  data_asof date,
  row_count integer not null default 0,
  status text not null default 'ready' check (status in ('ready'))
);

create table if not exists public.v4_ic_industry_metrics (
  batch_id text not null references public.v4_ic_industry_batch(batch_id) on delete cascade,
  version text not null,
  factor text not null,
  industry text not null,
  horizon integer not null check (horizon in (1, 3, 5, 10)),
  ic numeric,
  n integer not null default 0,
  n_days integer not null default 0,
  data_asof date,
  computed_at timestamptz not null default now(),
  primary key (batch_id, version, factor, industry, horizon)
);

create index if not exists v4_ic_industry_metrics_batch_idx
  on public.v4_ic_industry_metrics(batch_id, version, factor, industry, horizon);

alter table public.v4_ic_industry_batch enable row level security;
alter table public.v4_ic_industry_metrics enable row level security;

grant select on public.v4_ic_industry_batch to anon, authenticated;
grant select on public.v4_ic_industry_metrics to anon, authenticated;
grant all on public.v4_ic_industry_batch to service_role;
grant all on public.v4_ic_industry_metrics to service_role;

drop policy if exists "public read ic industry batches" on public.v4_ic_industry_batch;
create policy "public read ic industry batches"
  on public.v4_ic_industry_batch for select to anon, authenticated using (true);

drop policy if exists "public read ic industry metrics" on public.v4_ic_industry_metrics;
create policy "public read ic industry metrics"
  on public.v4_ic_industry_metrics for select to anon, authenticated using (true);
