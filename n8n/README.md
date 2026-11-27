# n8n shared raw cadence

Import `shared-raw-ssi-fhsc-schedule.json` into the existing n8n instance and select the existing GitHub HTTP Header Auth credential on all three HTTP Request nodes. Do not store the token in this JSON.

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

After import: attach the credential, run each HTTP node manually and confirm HTTP 204, verify that each manual trigger creates one `Unified SSI FHSC data production` run, then activate the workflow. GitHub Actions is the source of execution success/failure; n8n only owns schedules and dispatch acceptance.
