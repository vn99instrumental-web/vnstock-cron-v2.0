# VNStock generation 6 native flow

## Current state

Generation 6 uses final packages `vnstock==6.0.0` and `vnstock-oapi==0.1.1` in the isolated GitHub Actions environment `~/.venv_6x`. The legacy generation 4/5 runtime and ledgers remain untouched for historical comparison.

The source contract is explicit:

| Domain | Primary | Fallback | Notes |
| --- | --- | --- | --- |
| Reference | SSI | none | `Reference("ssi").equity.list()` |
| Market OHLCV | SSI | FHSC | fallback is used only after a typed/source error |
| Fundamental | FHSC | none | balance sheet, income statement and cash flow; currently verified but not included in the technical score |

The Vercel release is native-capable and `VNSTOCK6_NATIVE_MODE=1` makes the selected Gen6 source read only `output/serving/vnstock6/current`. It does not fall back to Supabase or the legacy serving root.

## Verified flows

- `vnstock6_source_diagnostic.yml`: read-only account, key, route and schema diagnostic. It never uploads raw data or credentials.
- `vnstock6_native_candidate.yml`: read-only end-to-end run; produces only a compact secret-free summary artifact.
- `vnstock6_native_production.yml`: n8n/manual entry point with `intraday`, `daily` and `weekly` modes. It publishes the Gen6 ledger and serving root under the shared `vnstock-main-writer` lock.
- Dashboard activation is a separate boolean input and defaults to false. Data can therefore be published before a Vercel release without breaking the bridge UI.

## Git data contract

Historical generation 4/5 prediction ledgers are immutable. Generation 6 writes to:

- `output/history/vnstock6/predictions/YYYY-MM-DD.jsonl`;
- `output/history/vnstock6/outcomes/YYYY-MM.jsonl`;
- shared canonical `output/ohlc/<symbol>.json`, merged by date with generation/source provenance on new bars;
- `output/vnstock6/native-status.json`;
- `output/serving/vnstock6/current`.

Each native signal records `pipeline_generation`, `reference_source`, `market_source`, `fundamental_source`, `fundamental_status` and `data_origin`.

## n8n handoff: five intraday runs

Use one active n8n Schedule Trigger in timezone `Asia/Ho_Chi_Minh`, weekdays only, with five local trigger times: `09:15`, `10:30`, `11:30`, `13:45` and `14:50`. Each trigger sends the same authenticated GitHub REST request:

- method: `POST`;
- URL: `https://api.github.com/repos/vn99instrumental-web/vnstock-cron-v2.0/actions/workflows/vnstock6_native_production.yml/dispatches`;
- GitHub credential: stored in n8n credential storage, never in the workflow JSON;
- body: `{"ref":"main","inputs":{"mode":"intraday","activate_dashboard":"true"}}`;
- headers: `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`.

The workflow concurrency group `vnstock-main-writer` queues overlapping calls. A successful run fetches SSI/FHSC data, writes a distinct minute-level snapshot, evaluates matured outcomes, publishes the Gen6 ledger/serving release, pushes `main`, then calls the authenticated Vercel revalidation endpoint. n8n should treat HTTP `204` from GitHub dispatch as accepted and alert only when dispatch fails; GitHub Actions remains the source of run success/failure.

For end-of-day or weekly maintenance, dispatch the same workflow manually with `mode=daily` or `mode=weekly`; those modes recompute the full IC/analysis layer. Do not run the legacy writer concurrently.
## Promotion gates

Promotion requires final package/version checks, account/device reuse, SSI and FHSC key checks, at least 80 successful universe symbols, complete native serving datasets, provenance validation, deterministic IDs, security review and web quality gates. A missing/invalid native manifest must fail visibly; the selected Gen6 source must never silently fall back to Supabase or the old GitHub serving root.

## Availability-aware scoring

`v6.1-availability` follows the production factor contract but is not numerically labelled as v4.18/v4.19. Each row records `factor_status`, `included_factors`, `excluded_factors`, `available_weight` and `missing_data_policy=exclude_and_renormalize`. A factor with incomplete inputs is excluded from both numerator and denominator. Current FHSC fundamental/growth data is connectivity/schema checked but not normalized per symbol, so both factors remain explicitly excluded until that ingestion is implemented.
