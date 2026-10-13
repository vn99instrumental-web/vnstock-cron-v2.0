-- Keep high-churn serving tables healthy after compact payload upserts.
-- Full source records remain in the Git ledger; Supabase stores the query-facing projection.
alter table public.v4_signals set (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02
);

comment on column public.v4_signals.breakdown is
  'Compact serving projection for dashboard/drill-down. Lossless prediction source remains in Git JSONL.';
