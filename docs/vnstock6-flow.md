# VNStock generation 6 dashboard flow

## Current milestone: explicit bridge

vnstock6 is a third dashboard source beside supabase and github. It is not
presented as native generation-6 scoring yet.

The manual vnstock6_compare.yml workflow currently:

1. reads the preserved production VCI reference snapshot without executing or
   modifying the older Python environment;
2. runs vnstock 6.0.0rc4 and vnstock-oapi 0.1.0rc3 in ~/.venv_6x,
   authenticates with GitHub Secrets, and reads the SSI reference universe;
3. publishes a secret-free comparison snapshot and
   output/vnstock6-preview/dashboard.json;
4. validates the public manifest and the upstream dashboard contract before
   committing either snapshot.

In bridge mode, all dashboard tabs use the existing GitHub serving datasets
filtered to symbols present in the SSI reference universe. Aggregate IC and
diagnostic datasets remain the upstream GitHub values. The UI displays this
limitation on every page and never silently falls back when the generation-6
manifest is missing or invalid.

## Target native flow

The bridge may be replaced only when these stages have their own generation-6
artifacts and pass contract validation:

| Stage | Input | Independent output | Current status |
| --- | --- | --- | --- |
| authenticate | GitHub Secrets scoped to one step | authenticated process only | native |
| reference | SSI Open API | normalized SSI universe | native |
| market ingest | SSI Open API | OHLC, quotes, trades and supported market features | pending |
| scoring | normalized generation-6 inputs | predictions and outcomes ledger | pending |
| serving | generation-6 ledger | metadata, today, buy, history, analysis, IC and charts | bridge |

The native serving root will be output/serving/vnstock6/current. The web adapter
must switch from mode=bridge to mode=native only after all required datasets
are present and validated.

## Independence rules

- Keep ~/.venv_6x separate from /opt/vnstock/.venv.
- Do not import vnstock_data, vnstock_ta, vnai or other older-generation
  packages in generation-6 jobs.
- Every market call names SSI explicitly.
- Never copy credentials into artifacts, logs, client bundles or committed
  files.
- Never label production VCI scoring as native generation-6 output.
- Do not fall back to Supabase/GitHub after vnstock6 is selected; expose an
  unavailable/error state instead.
- Generation-6 jobs may share the repository writer lock for Git safety, but
  data collection, scoring, caches and output paths must remain independent.
- Promotion to a scheduled autonomous workflow requires successful checks for
  schema, row counts, freshness, symbol coverage, deterministic IDs and
  dashboard dataset completeness.