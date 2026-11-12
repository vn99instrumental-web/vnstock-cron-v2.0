# VNStock generation 6 native flow

## Current state

Generation 6 uses final packages `vnstock==6.0.0` and `vnstock-oapi==0.1.1` in the isolated GitHub Actions environment `~/.venv_6x`. The legacy generation 4/5 runtime and ledgers remain untouched for historical comparison.

The source contract is explicit:

| Domain | Primary | Fallback | Notes |
| --- | --- | --- | --- |
| Reference | SSI | none | `Reference("ssi").equity.list()` |
| Market OHLCV | SSI | FHSC | fallback is used only after a typed/source error |
| Fundamental | FHSC | none | balance sheet, income statement and cash flow; currently verified but not included in the technical score |

The public dashboard manifest remains `mode=bridge` until the compatible web release is approved for Vercel. Native data is already isolated under `output/serving/vnstock6/current` and can be inspected without switching the deployed dashboard.

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

## n8n handoff

Dispatch `.github/workflows/vnstock6_native_production.yml` with:

| Existing cadence | Input |
| --- | --- |
| Intraday runs | `mode=intraday`, `activate_dashboard=false` |
| End-of-day data run | `mode=daily`, `activate_dashboard=false` |
| Weekly evaluation/IC run | `mode=weekly`, `activate_dashboard=false` |

Keep `activate_dashboard=false` until the native-capable web commit has been deployed to Vercel and verified. Do not dispatch old and Gen6 writer workflows concurrently.

## Promotion gates

Promotion requires final package/version checks, account/device reuse, SSI and FHSC key checks, at least 80 successful universe symbols, complete native serving datasets, provenance validation, deterministic IDs, security review and web quality gates. A missing/invalid native manifest must fail visibly; the selected Gen6 source must never silently fall back to Supabase or the old GitHub serving root.

## Known scoring constraint

`v6.0-native` currently scores EMA, RSI, 20-day return, volume ratio and 52-week range. FHSC fundamentals are connectivity/schema checked and tagged as `available_not_scored` when healthy, but are not yet part of the score. This version must not be described as numerically equivalent to v4.18/v4.19.
