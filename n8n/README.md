# n8n shared raw cadence

Import `shared-raw-ssi-fhsc-schedule.json` into the existing n8n instance and select the existing GitHub HTTP Header Auth credential on all three HTTP Request nodes. Do not store the token in this JSON.

Schedule timezone: `Asia/Ho_Chi_Minh`.

- Intraday, Monday-Friday: 09:25, 10:25, 11:25, 13:25, 14:25.
- Daily, Monday-Friday: 15:05.
- Weekly, Sunday: 07:15.

Every trigger dispatches only `shared_raw_ssi_fhsc.yml` with `cadence=intraday|daily|weekly`. GitHub publishes one immutable raw release, then fans the exact `raw_release_id` out to SSI and the matching Gen 6 calculator. The calculators never dispatch provider collection themselves.

Retry policy: **collect once, calculate many**. Retry the failed consumer with the existing `raw_release_id`; never rerun the shared collector merely because a formula, build or publish step failed.

Required GitHub credential permissions for repository `vn99instrumental-web/vnstock-cron-v2.0`:

- Actions: read and write.
- Metadata: read.

After import: attach the credential, run each HTTP node manually and confirm HTTP 204, then activate the workflow. GitHub Actions is the source of execution success/failure; n8n only owns schedules and dispatch acceptance.
