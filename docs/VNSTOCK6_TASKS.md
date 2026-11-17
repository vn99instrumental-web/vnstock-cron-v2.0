# VNStock 6 production task list

Updated: 2026-11-17

## Completed

- [x] Final Gen 6 packages are pinned in an isolated GitHub Actions environment.
- [x] SSI is the only reference/OHLCV source; approved market-factor routes use SSI first and FHSC only for documented fallback/order-book gaps.
- [x] Technical indicators use vnstock_quant.ta.
- [x] Balance sheet, income statement and cash flow feed vnstock_quant.fa ratios and growth.
- [x] Missing factors are excluded and available weights are renormalized.
- [x] Native Git ledger and isolated serving root feed all dashboard tabs.
- [x] The n8n workflow owns all five weekday intraday dispatches plus daily and weekly dispatches.
- [x] Intraday fetches only market data and reuses the committed fundamental cache.
- [x] Existing OHLC files use a 14-day correction window instead of refetching 500 days five times per day.
- [x] Daily outcomes and full analytics run separately at 16:15 ICT on weekdays.
- [x] Daily post-market maintenance checks BCTC signatures for every symbol and recalculates only changed statements before the closing score.
- [x] SSI reference and FHSC statements refresh separately at 09:15 ICT on Sundays.
- [x] A failed weekly statement refresh preserves the last successful symbol cache.
- [x] Fundamental cache entries older than the active 3/30-day TTL fail closed and are excluded from scoring.

- [x] Add ADX(14), Supertrend(10,3), `s_trend_st` and BCTC cash-flow fields to ledger and dashboard serving.
- [x] Add all 17 production-reference signals, including cash flow, foreign flow, order-flow phase, proprietary, insider and depth.
- [x] Preserve raw proprietary/insider values, source/as-of provenance and explicit unavailable/error states in dashboard serving.
- [x] Keep BCTC and FHSC proprietary/insider endpoint refreshes out of intraday; intraday reads their caches.
- [x] Rebuild/revalidate weekly serving only when full BCTC refresh detects material content changes.

## Operational checks after merge

Bootstrap evidence: production run 43338517181 refreshed FHSC and vnstock_quant factors for 100/100 symbols and published commit fe613b7a; candidate run 43350815066 passed with SSI 100/100, FHSC sample 3/3 and availability-aware scoring.

- [ ] Confirm the revised material-change weekly workflow completes within its 180-minute timeout and takes both changed/unchanged branches correctly.
- [x] Confirm fundamental-factors.json and fundamental-status.json are committed without secret fields (daily run 43353614220, commit 92008e54).
- [x] Confirm the next intraday run consumes the refreshed cache and publishes v6.2-quant (run 43350792238).
- [x] Confirm the first daily maintenance run publishes outcomes, IC and analysis and revalidates Vercel (run 43353614220).
- [ ] Verify raw proprietary/insider/order-flow provenance and missing-factor explanations in the authenticated Gen6 dashboard after deployment.

## Migration and quality gates

- [ ] Build the formal migration inventory and contract report from saved legacy ledgers; the retired legacy APIs cannot be queried live.
- [ ] Remove or archive the RC preview branch in debug.yml.
- [ ] Prevent the manual bridge comparison workflow from overwriting a native dashboard manifest.
- [ ] Accumulate at least 30 forward sessions before using v6.2 as the sole scoring reference.
- [ ] Monitor coverage, IC and missing-factor rates; do not treat missing data as zero.
- [ ] Resolve remaining source coverage gaps (`s_prop_5d` 99/100 and `s_insider` 74/100 in the latest committed snapshot) without converting missing responses to zero.
- [ ] Replace the remaining audited legacy cash-flow overlays with native Gen6 BCTC values as FHSC refreshes succeed.

## Cadence ownership

- n8n owns all schedules: five intraday dispatches, weekday daily maintenance and Sunday slow-source refresh.
- GitHub Actions workflows are dispatch-only executors and contain no independent cron schedule.
- All writers share vnstock-main-writer so Git commits are serialized.
