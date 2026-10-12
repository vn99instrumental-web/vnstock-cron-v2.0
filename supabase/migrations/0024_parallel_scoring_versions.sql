-- Store v4.1-v4.18 side by side for the same symbol/snapshot.
-- v4.18 remains the only production feed used by Buy and Analysis.

begin;

alter table public.v4_signals
  alter column scoring_version set not null;
alter table public.v4_outcomes
  alter column scoring_version set not null;

alter table public.v4_signals
  drop constraint if exists v4_signals_symbol_signal_date_snap_time_key;
alter table public.v4_signals
  add constraint v4_signals_symbol_date_snap_version_key
  unique (symbol, signal_date, snap_time, scoring_version);

alter table public.v4_outcomes
  drop constraint if exists v4_outcomes_symbol_signal_date_snap_time_lens_key;
alter table public.v4_outcomes
  add constraint v4_outcomes_symbol_date_snap_lens_version_key
  unique (symbol, signal_date, snap_time, lens, scoring_version);

create index if not exists idx_v4_signals_version_date_snap
  on public.v4_signals (scoring_version, signal_date desc, snap_time desc);
create index if not exists idx_v4_outcomes_version_date_snap
  on public.v4_outcomes (scoring_version, signal_date desc, snap_time);
create index if not exists idx_v4_runs_version_started
  on public.v4_runs (scoring_version, started_at desc);

create or replace view public.v4_signals_production
with (security_invoker = true)
as
select *
from public.v4_signals
where scoring_version = 'v4.18';

revoke all on public.v4_signals_production from anon, authenticated;
grant select on public.v4_signals_production to anon, authenticated;

-- Keep production-only screens isolated from the 17 shadow versions while
-- retaining their existing, verified calculations and output columns.
do $$
declare
  view_name text;
  definition text;
begin
  foreach view_name in array array[
    'v4_buy_robustness',
    'v4_signal_analysis_feed'
  ] loop
    select pg_get_viewdef(format('public.%I', view_name)::regclass, true)
      into definition;
    definition := replace(definition, 'v4_signals', 'v4_signals_production');
    execute format(
      'create or replace view public.%I with (security_invoker = true) as %s',
      view_name, definition
    );
  end loop;
end
$$;

-- IC views must pair a signal only with the outcome from the same scoring
-- version. Without this predicate, parallel versions create a cross product.
do $$
declare
  view_name text;
  definition text;
begin
  foreach view_name in array array[
    'v4_ic_by_indicator',
    'v4_ic_by_industry',
    'v4_ic_by_industry_ver',
    'v4_ic_by_factor_ver',
    'v4_ic_by_industry_factor_ver'
  ] loop
    select pg_get_viewdef(format('public.%I', view_name)::regclass, true)
      into definition;
    definition := replace(
      definition,
      'AND o.lens = ''trade''::text',
      'AND o.lens = ''trade''::text AND o.scoring_version = s.scoring_version'
    );
    execute format(
      'create or replace view public.%I with (security_invoker = true) as %s',
      view_name, definition
    );
  end loop;
end
$$;

commit;
