# VNStock generation 6 native flow

## Current state

Generation 6 uses final packages `vnstock==6.0.0`, `vnstock-oapi==0.1.1` and `vnstock_quant==1.0.0` in the isolated GitHub Actions environment `~/.venv_6x`. Exact pins and the private extra index make every GitHub Actions run reproducible. The legacy generation 4/5 runtime and ledgers remain untouched for historical comparison.
The source contract is explicit:

| Domain | Primary | Fallback | Notes |
| --- | --- | --- | --- |
| Reference | SSI | none | `Reference("ssi").equity.list()` |
| Market OHLCV | SSI | none | intraday and daily-close market data stay on the verified SSI flow |
| Fundamental | FHSC | none | quarterly balance sheet, income statement and cash flow; ratios and growth are calculated by `vnstock_quant.fa` per symbol |
| Foreign flow | SSI | FHSC | refreshed on each scoring run; source and as-of date are retained |
| Session statistics | SSI | FHSC active-session | intraday turnover and average trade size only |
| Order book | FHSC | none | intraday only because Gen6 has no SSI order-book reader |
| Proprietary/insider | FHSC | last-known-good cache | source endpoints are called only by post-market daily maintenance |
The Vercel release is native-capable and `VNSTOCK6_NATIVE_MODE=1` makes the selected Gen6 source read only `output/serving/vnstock6/current`. It does not fall back to Supabase or the legacy serving root.

## Verified flows

- `vnstock6_source_diagnostic.yml`: read-only account, key, route and schema diagnostic. It never uploads raw data or credentials.
- `vnstock6_native_candidate.yml`: read-only end-to-end run; produces only a compact secret-free summary artifact.
- `vnstock6_native_production.yml`: n8n/manual intraday executor. It publishes the Gen6 ledger and serving root under the shared `vnstock-main-writer` lock.
- `vnstock6_daily_maintenance.yml`: post-market executor for BCTC change detection, slow market factors, closing scores, outcomes and full serving rebuild.
- `vnstock6_fundamental_refresh.yml`: weekly full-universe BCTC safety net; it recalculates and revalidates the dashboard only when material statement/factor content changes.
- Dashboard activation is a separate boolean input and defaults to true for the production workflow. It can be disabled explicitly for a data-only run.
## Git data contract

Historical generation 4/5 prediction ledgers are immutable. Generation 6 writes to:

- `output/history/vnstock6/predictions/YYYY-MM-DD.jsonl`;
- `output/history/vnstock6/outcomes/YYYY-MM.jsonl`;
- shared canonical `output/ohlc/<symbol>.json`, merged by date with generation/source provenance on new bars;
- `output/vnstock6/native-status.json`;
- `output/serving/vnstock6/current`.

Each native signal records `pipeline_generation`, `reference_source`, `market_source`, `fundamental_source`, `fundamental_status`, `data_origin`, `calculation_engine`, `calculation_version`, technical indicator output, factor availability and excluded-factor reasons.
## n8n schedule ownership

The active n8n workflow owns all Gen 6 schedules in timezone `Asia/Ho_Chi_Minh`: five weekday intraday dispatches at `09:15`, `10:30`, `11:30`, `13:45` and `14:50`, weekday daily maintenance at `16:15`, and the full slow-source refresh at `09:15` on Sunday. GitHub Actions workflows are dispatch-only executors and contain no `schedule` trigger.

Each intraday trigger sends this authenticated GitHub REST request:

- method: `POST`;
- URL: `https://api.github.com/repos/vn99instrumental-web/vnstock-cron-v2.0/actions/workflows/vnstock6_native_production.yml/dispatches`;
- GitHub credential: stored in n8n credential storage, never in the workflow JSON;
- body: `{"ref":"main","inputs":{"mode":"intraday","activate_dashboard":"true"}}`;
- headers: `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`.

The workflow concurrency group vnstock-main-writer queues overlapping calls. An intraday run fetches SSI OHLCV, SSI foreign/session statistics, and the approved FHSC order book (with FHSC foreign/active-session fallback when SSI is unavailable). It calculates technical indicators, scores with committed BCTC/proprietary/insider caches, publishes the Gen6 ledger/serving release, pushes main, then calls the authenticated Vercel revalidation endpoint. It never calls BCTC, proprietary-flow or insider endpoints. n8n should treat HTTP 204 from GitHub dispatch as accepted and alert only when dispatch fails; GitHub Actions remains the source of run success/failure.

## Data cadence

| Cadence | Workflow | External reads | Derived work |
| --- | --- | --- | --- |
| Five weekday runs at 09:15, 10:30, 11:30, 13:45, 14:50 ICT | vnstock6_native_production.yml dispatched by n8n with mode=intraday | SSI OHLCV/foreign/session; approved FHSC order book and bounded fallbacks; no BCTC/proprietary/insider calls | fast technical/flow/depth signals, scoring, incremental serving and Vercel revalidation |
| Weekdays at 16:15 ICT | vnstock6_daily_maintenance.yml | BCTC update probes, FHSC proprietary/insider, SSI daily-close OHLCV/foreign; cached in-session depth | recalculate changed BCTC, closing score, outcomes, analytics/serving and Vercel revalidation |
| Sundays at 09:15 ICT | vnstock6_fundamental_refresh.yml | SSI reference plus FHSC balance sheet, income statement and cash flow | full BCTC safety refresh; rebuild scores/serving and revalidate only on material change |

All three writers share vnstock-main-writer; overlapping jobs queue instead of writing Git concurrently. n8n is the single schedule owner, while GitHub Actions performs the dispatched work. Do not run the legacy writer concurrently.

## Promotion gates

Promotion requires final package/version checks, account/device reuse, SSI and FHSC key checks, at least 80 successful universe symbols, complete native serving datasets, provenance validation, deterministic IDs, security review and web quality gates. A missing/invalid native manifest must fail visibly; the selected Gen6 source must never silently fall back to Supabase or the old GitHub serving root.

## Availability-aware scoring

`v6.2-quant` follows the production factor contract but is not numerically labelled as v4.18/v4.19. EMA, RSI, ATR and OBV are calculated by `vnstock_quant.ta`; FHSC statements feed `vnstock_quant.fa` ratios and quarterly year-over-year growth. Each row records `factor_status`, `included_factors`, `excluded_factors`, `available_weight` and `missing_data_policy=exclude_and_renormalize`. A factor with incomplete inputs is marked with its reason and excluded from both numerator and denominator, so an unavailable source never becomes a fabricated zero.

## Fundamental refresh policy

FHSC throttles statement reads, so fundamentals are not re-downloaded during each of the five intraday runs. The production cache is `output/vnstock6/fundamental-factors.json` and carries source, calculation version, refresh time, ratios and statement quality counts per symbol.

- Candidate refreshes three symbols through the dedicated fundamental command. It reports `PASS_DEGRADED` when FHSC is unavailable only if fundamental and growth factors are explicitly excluded.
- Daily maintenance checks all configured symbols after market close. A deterministic signature of balance sheet, income statement and cash-flow content is compared with the committed cache; unchanged statements update only `checked_at`, while changed statements recalculate ratios, growth and cash-flow factors with `vnstock_quant.fa`.
- Intraday mode never calls the three statement endpoints, `proprietary_flow` or `insider_deal`. It reads their last committed caches; FHSC use is limited to order book and the approved foreign/active-session fallbacks.
- Weekly refresh recalculates the full FHSC universe as a safety net. Read failures preserve last-known-good data; missing or expired values are excluded and available weights are renormalized, never replaced by zero. Refresh timestamps are ignored for change detection; only material content changes trigger scoring, serving rebuild and Vercel revalidation.


## Indicator upgrade (2026-11-13)

Gen6 publishes all 17 production-reference signals. ADX(14) and Supertrend(10,3) use the auditable `local_wilder_reference` implementation when Community `vnstock_quant.ta` returns `QUANT_TIER_REQUIRED`. Foreign flow and depth refresh intraday; proprietary and insider refresh post-market and are cached intraday; BCTC-derived fundamental, cash-flow and growth signals refresh only after statement checks/full weekly refresh. Empty or unclassified source responses remain unavailable and are excluded rather than converted to zero. The dashboard includes raw values, source/as-of provenance and exclusion reasons where available.
