-- Historical IC for explicitly retrospective shadow rows.
-- Kept separate from v4_ic_metrics so backtest evidence cannot be mistaken
-- for independently matured forward IC.

create table if not exists public.v4_ic_backfill_metrics (
  config_version text not null,
  factor text not null,
  horizon integer not null,
  sample_kind text not null check (sample_kind = 'retrospective_backfill'),
  source_version text not null,
  signal_date_min date not null,
  signal_date_max date not null,
  ic numeric,
  n integer not null check (n >= 0),
  computed_at timestamptz not null default now(),
  primary key (config_version, factor, horizon, sample_kind)
);

alter table public.v4_ic_backfill_metrics enable row level security;

drop policy if exists "read v4 ic backfill" on public.v4_ic_backfill_metrics;
create policy "read v4 ic backfill"
on public.v4_ic_backfill_metrics
for select
to anon, authenticated
using (true);

revoke all on table public.v4_ic_backfill_metrics from public;
grant select on table public.v4_ic_backfill_metrics to anon, authenticated;
grant all on table public.v4_ic_backfill_metrics to service_role;

create index if not exists idx_v4_ic_backfill_metrics_version_horizon
on public.v4_ic_backfill_metrics(config_version, horizon, factor);

comment on table public.v4_ic_backfill_metrics is
  'Historical IC for retrospective shadow scores, separated from forward v4_ic_metrics.';
comment on column public.v4_ic_backfill_metrics.source_version is
  'Version whose already-matured outcome is joined through shadow_backfill_source_pred_id.';
comment on column public.v4_ic_backfill_metrics.sample_kind is
  'Explicit provenance; currently only retrospective_backfill is allowed.';

