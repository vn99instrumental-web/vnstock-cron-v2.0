-- Keep Supabase as a dashboard serving layer, not a lossless archive.
-- Git ledger remains the recoverable source for all historical scoring versions.

begin;

delete from public.v4_outcomes
where scoring_version not in ('v4.18', 'v4.17', 'v4.9', 'v4.8', 'v4.1', 'v2.3');

delete from public.v4_signals
where scoring_version not in ('v4.18', 'v4.17', 'v4.9', 'v4.8', 'v4.1', 'v2.3');

delete from public.v4_runs
where scoring_version not in ('v4.18', 'v4.17', 'v4.9', 'v4.8', 'v4.1', 'v2.3');

delete from public.v4_ic_metrics
where config_version not in ('v4.18', 'v4.17', 'v4.9', 'v4.8', 'v4.1', 'v2.3');

delete from public.v4_marginal_ic
where version not in ('v4.18', 'v4.17', 'v4.9', 'v4.8', 'v4.1', 'v2.3');

-- One ready batch is sufficient because publication is atomic and Git can rebuild it.
delete from public.v4_ic_industry_batch b
where b.batch_id <> (
  select batch_id
  from public.v4_ic_industry_batch
  where status = 'ready'
  order by computed_at desc
  limit 1
);

-- UI only needs a bounded price history for EMA200 and charts.
delete from public.v4_ohlc
where date < current_date - 900;

analyze public.v4_outcomes;
analyze public.v4_signals;
analyze public.v4_runs;
analyze public.v4_ic_metrics;
analyze public.v4_marginal_ic;
analyze public.v4_ic_industry_batch;
analyze public.v4_ic_industry_metrics;
analyze public.v4_ohlc;

commit;