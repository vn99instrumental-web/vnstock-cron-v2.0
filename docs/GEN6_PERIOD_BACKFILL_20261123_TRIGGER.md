# Gen6 source-backed reporting-period repair — 2026-11-23

This file is a **one-time push-to-main trigger** for `vnstock6_period_backfill_20261123.yml`.
Keep it unchanged after the first merge. Use the manual `workflow_dispatch` to retry
after fixing source availability or a transient quality failure.

## Root cause
A full FHSC refresh calculated factors but did not retain statement period metadata
because the incremental `latest_statement_probe` was skipped. The failed Gen6 candidate
had `growth_period=3/300` and `cash_flow_period=96/300` rows, below the strict
minimum `80 symbols × 3 profiles = 240 rows`.

## Changes
- Extract actual reporting quarters directly from fully downloaded normalized FHSC
  income-statement, balance-sheet, and cash-flow rows; normalize `2026Q3`,
  `2026-Q3`, or quarter-end ISO date to `2026-Q3`.
- Unknown source periods remain null. Never use today's date as a substitute.
- Preserve source periods in fundamental cache, scoring rows, and dashboard serving.
- For daily materialization, prefer source full-statement metadata; use daily probe
  only when full metadata is unavailable. An unchanged probe still refreshes the
  metadata on cached values.
- Leave all scoring formulas, weights, and mandatory candidate thresholds intact.

## Acceptance and rollback safety
1. PR unit tests cover parsing, full materialization, full refresh, and daily probe.
2. Full FHSC backfill verifies at least 80/100 configured symbols have both periods.
3. Backfilled cache is committed **only** after cache validation and period coverage pass.
4. A new native SSI intraday candidate must pass the original strict validator,
   including both periods ≥240/300 and zero invalid fields, before serving is published.
5. Failed steps do not overwrite the last-good serving; failure diagnostics are uploaded.
6. Public dashboard revalidation occurs only after successful serving publication.

The one-time workflow can be rerun manually in a **market session** for fresh
order-book/depth fields. A run outside the session may safely fail the strict
same-session depth gate; do not weaken the quality gate.
