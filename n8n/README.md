# n8n shared raw cadence

Import `shared-raw-ssi-fhsc-schedule.json` into the existing n8n instance and select the existing predefined **GitHub API** credential on all three HTTP Request nodes. Do not store the credential ID or token in this JSON.

Schedule timezone: `Asia/Ho_Chi_Minh`.

- Intraday, Monday-Friday: 09:25, 10:25, 11:25, 13:25, 14:25.
- Daily, Monday-Friday: 15:05.
- Weekly, Sunday: 07:15.

Every trigger dispatches only `shared_raw_ssi_fhsc.yml` with `cadence=intraday|daily|weekly` and `engine=both`. One n8n trigger therefore creates exactly one GitHub Actions run. Inside that run GitHub collects and publishes one immutable raw release, then executes the Gen 6 and SSI calculators sequentially from the exact same `raw_release_id`. It does not dispatch child workflows, and the calculators never dispatch provider collection themselves.

Retry policy: **collect once, calculate many**. Manually dispatch the same workflow with the existing `raw_release_id` plus `engine=gen6`, `engine=ssi`, or `engine=both`; never rerun the shared collector merely because a formula, build or publish step failed.

Before activation, disable the legacy n8n nodes/workflows that dispatch `vnstock6_native_production.yml`, `vnstock6_daily_maintenance.yml`, `vnstock6_fundamental_refresh.yml`, or `ssi_independent_production.yml` directly. Leaving a legacy dispatcher active would duplicate calculations and GitHub runs.

Required GitHub credential permissions for repository `vn99instrumental-web/vnstock-cron-v2.0`:

- Actions: read and write.
- Metadata: read.

Live deployment (2026-11-27): workflow `Unified SSI FHSC data cadence` (`RPjryobbCgj9dcOLM`) is published with the predefined `GitHub account` credential. The legacy Gen 6 daily, intraday and weekly workflows and their dated backups are unpublished. Do not execute all three HTTP nodes just to test credentials because that creates three real provider runs. Test one node with a stored `raw_release_id`, confirm HTTP 204, then verify the single GitHub run.

GitHub Actions is the source of execution success/failure; n8n only owns schedules and dispatch acceptance. Production daily run `45962958727` collected release `20261127T080622Z-bd6870bd` once, then completed Gen 6, SSI, separate publish and one Vercel revalidation successfully.
