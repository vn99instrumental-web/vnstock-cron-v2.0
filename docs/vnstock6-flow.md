# VNStock generation 6 native flow

## Current state

Generation 6 uses final packages `vnstock==6.0.0`, `vnstock-oapi==0.1.1` and `vnstock_quant==1.0.0` in the isolated GitHub Actions environment `~/.venv_6x`. Exact pins and the private extra index make every GitHub Actions run reproducible. The legacy generation 4/5 runtime and ledgers remain untouched for historical comparison.
The source contract is explicit:

| Domain | Primary | Fallback | Notes |
| --- | --- | --- | --- |
| Reference | SSI | none | `Reference("ssi").equity.list()` |
| Market OHLCV | SSI | FHSC | fallback is used only after a typed/source error |
| Fundamental | FHSC | none | quarterly balance sheet, income statement and cash flow; ratios and growth are calculated by `vnstock_quant.fa` per symbol |
The Vercel release is native-capable and `VNSTOCK6_NATIVE_MODE=1` makes the selected Gen6 source read only `output/serving/vnstock6/current`. It does not fall back to Supabase or the legacy serving root.

## Verified flows

- `vnstock6_source_diagnostic.yml`: read-only account, key, route and schema diagnostic. It never uploads raw data or credentials.
- `vnstock6_native_candidate.yml`: read-only end-to-end run; produces only a compact secret-free summary artifact.
- `vnstock6_native_production.yml`: n8n/manual entry point with `intraday`, `daily` and `weekly` modes. It publishes the Gen6 ledger and serving root under the shared `vnstock-main-writer` lock.
- Dashboard activation is a separate boolean input and defaults to true for the production workflow. It can be disabled explicitly for a data-only run.
## Git data contract

Historical generation 4/5 prediction ledgers are immutable. Generation 6 writes to:

- `output/history/vnstock6/predictions/YYYY-MM-DD.jsonl`;
- `output/history/vnstock6/outcomes/YYYY-MM.jsonl`;
- shared canonical `output/ohlc/<symbol>.json`, merged by date with generation/source provenance on new bars;
- `output/vnstock6/native-status.json`;
- `output/serving/vnstock6/current`.

Each native signal records `pipeline_generation`, `reference_source`, `market_source`, `fundamental_source`, `fundamental_status`, `data_origin`, `calculation_engine`, `calculation_version`, technical indicator output, factor availability and excluded-factor reasons.
## n8n handoff: five intraday runs

Use one active n8n Schedule Trigger in timezone `Asia/Ho_Chi_Minh`, weekdays only, with five local trigger times: `09:15`, `10:30`, `11:30`, `13:45` and `14:50`. Each trigger sends the same authenticated GitHub REST request:

- method: `POST`;
- URL: `https://api.github.com/repos/vn99instrumental-web/vnstock-cron-v2.0/actions/workflows/vnstock6_native_production.yml/dispatches`;
- GitHub credential: stored in n8n credential storage, never in the workflow JSON;
- body: `{"ref":"main","inputs":{"mode":"intraday","activate_dashboard":"true"}}`;
- headers: `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`.

The workflow concurrency group vnstock-main-writer queues overlapping calls. An intraday run fetches market OHLCV only, writes a distinct minute-level snapshot, scores with the committed fundamental cache, publishes the Gen6 ledger/serving release, pushes main, then calls the authenticated Vercel revalidation endpoint. n8n should treat HTTP 204 from GitHub dispatch as accepted and alert only when dispatch fails; GitHub Actions remains the source of run success/failure.

## Data cadence

| Cadence | Workflow | External reads | Derived work |
| --- | --- | --- | --- |
| Five weekday runs at 09:15, 10:30, 11:30, 13:45, 14:50 ICT | vnstock6_native_production.yml dispatched by n8n with mode=intraday | SSI OHLCV with FHSC fallback; only a 14-day correction window after bootstrap | technical indicators, scoring, incremental serving and Vercel revalidation |
| Weekdays at 16:15 ICT | vnstock6_daily_maintenance.yml | none | matured outcomes, full IC/analysis, full serving and Vercel revalidation |
| Sundays at 09:15 ICT | vnstock6_fundamental_refresh.yml | SSI reference plus FHSC balance sheet, income statement and cash flow | vnstock_quant.fa ratios/growth and the committed fundamental cache |

All three writers share vnstock-main-writer; overlapping jobs queue instead of writing Git concurrently. The daily and weekly schedules are GitHub Actions schedules, while the existing five intraday triggers remain in n8n. Do not run the legacy writer concurrently.

## Promotion gates

Promotion requires final package/version checks, account/device reuse, SSI and FHSC key checks, at least 80 successful universe symbols, complete native serving datasets, provenance validation, deterministic IDs, security review and web quality gates. A missing/invalid native manifest must fail visibly; the selected Gen6 source must never silently fall back to Supabase or the old GitHub serving root.

## Availability-aware scoring

`v6.2-quant` follows the production factor contract but is not numerically labelled as v4.18/v4.19. EMA, RSI, ATR and OBV are calculated by `vnstock_quant.ta`; FHSC statements feed `vnstock_quant.fa` ratios and quarterly year-over-year growth. Each row records `factor_status`, `included_factors`, `excluded_factors`, `available_weight` and `missing_data_policy=exclude_and_renormalize`. A factor with incomplete inputs is marked with its reason and excluded from both numerator and denominator, so an unavailable source never becomes a fabricated zero.

## Fundamental refresh policy

FHSC throttles statement reads, so fundamentals are not re-downloaded during each of the five intraday runs. The production cache is `output/vnstock6/fundamental-factors.json` and carries source, calculation version, refresh time, ratios and statement quality counts per symbol.

- Candidate refreshes three symbols through the dedicated fundamental command to prove the live FHSC and vnstock_quant.fa path, then validates at least one scored fundamental row.
- The weekly workflow refreshes the full configured universe and may run for up to 180 minutes. A failed refresh preserves the prior cache entry and records a secret-free failure status.
- Intraday mode never calls the three statement endpoints. It reads the last committed cache and refetches only the recent OHLCV correction window.
- A missing cache entry is marked fundamental_cache_unavailable; an entry older than 14 days is marked fundamental_cache_stale. Both fundamental factors are excluded and the available weights are renormalized, never replaced by zero.
