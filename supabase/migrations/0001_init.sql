-- 0001_init.sql — VNStock Signals App schema
-- Postgres 17 · project mcaqnaomzoqgxccdgvls
-- Prefix v4_ để tách khỏi các app khác đang share project này.
-- Ghi: chỉ service_role (bypass RLS). Đọc: anon/authenticated qua policy SELECT.

-- ============ RUNS ============
create table if not exists public.v4_runs (
  run_id           text primary key,
  kind             text not null,               -- 'intraday' | 'daily'
  started_at       timestamptz not null default now(),
  scoring_version  text,
  gate_version     text,
  universe_size    int,
  n_buy            int,
  health           jsonb
);

-- ============ SIGNALS (mirror ledger predictions) ============
create table if not exists public.v4_signals (
  id                  bigint generated always as identity primary key,
  run_id              text references public.v4_runs(run_id),
  signal_date         date not null,
  snap_time           timestamptz not null,
  symbol              text not null,
  regime              text,
  decision            text,                      -- BUY | STRONG BUY | HOLD | ...
  score_trade         numeric,
  pre_total           numeric,
  extras              numeric,
  w_reg               numeric,
  breakdown           jsonb,                     -- per-factor raw/norm/weight/gate/contribution + extras + V4_EXTRA
  -- shadow fields
  decision_nomr       text,
  score_trade_nomr    numeric,
  mr_delta            numeric,
  decision_altfund    text,
  score_trade_altfund numeric,
  extras_guard_flag   boolean,
  -- trade levels
  entry               numeric,
  stop                numeric,
  tp1                 numeric,
  scoring_version     text,
  gate_version        text,
  unique (symbol, signal_date, snap_time)
);
create index if not exists idx_v4_signals_date     on public.v4_signals (signal_date desc);
create index if not exists idx_v4_signals_symbol   on public.v4_signals (symbol);
create index if not exists idx_v4_signals_decision on public.v4_signals (decision);
create index if not exists idx_v4_signals_run      on public.v4_signals (run_id);

-- ============ OUTCOMES (mirror ledger outcomes) ============
create table if not exists public.v4_outcomes (
  id           bigint generated always as identity primary key,
  symbol       text not null,
  signal_date  date not null,
  horizon      int not null,                     -- 1, 5, ...
  ret          numeric,
  matured_at   timestamptz,
  unique (symbol, signal_date, horizon)
);
create index if not exists idx_v4_outcomes_sym_date on public.v4_outcomes (symbol, signal_date);

-- ============ SCORING CONFIGS (versioned, editable) ============
create table if not exists public.v4_scoring_configs (
  id              bigint generated always as identity primary key,
  version_label   text not null unique,
  status          text not null default 'draft', -- draft | shadow | production | archived
  factor_weights  jsonb not null,
  gate_matrix     jsonb not null,                -- factor -> [UP, SIDE, DOWN, DEEP]
  thresholds      jsonb not null,
  extras_cfg      jsonb,
  notes           text,
  created_at      timestamptz not null default now(),
  promoted_at     timestamptz
);
create index if not exists idx_v4_configs_status on public.v4_scoring_configs (status);

-- ============ IC METRICS (Python evaluator ghi) ============
create table if not exists public.v4_ic_metrics (
  id              bigint generated always as identity primary key,
  config_version  text,
  factor          text,
  horizon         int,
  ic              numeric,
  n               int,
  computed_at     timestamptz not null default now(),
  unique (config_version, factor, horizon)
);

-- ============ RLS ============
alter table public.v4_runs           enable row level security;
alter table public.v4_signals        enable row level security;
alter table public.v4_outcomes       enable row level security;
alter table public.v4_scoring_configs enable row level security;
alter table public.v4_ic_metrics     enable row level security;

-- Đọc công khai (repo vốn public; data screening không nhạy cảm).
create policy "read v4_runs"     on public.v4_runs      for select to anon, authenticated using (true);
create policy "read v4_signals"  on public.v4_signals   for select to anon, authenticated using (true);
create policy "read v4_outcomes" on public.v4_outcomes  for select to anon, authenticated using (true);
create policy "read v4_ic"       on public.v4_ic_metrics for select to anon, authenticated using (true);
-- Config gate sau đăng nhập.
create policy "read v4_configs"  on public.v4_scoring_configs for select to authenticated using (true);

-- KHÔNG có policy INSERT/UPDATE/DELETE cho anon/authenticated:
-- mọi ghi đi qua service_role (server-side sync + Promote), service_role bypass RLS.
