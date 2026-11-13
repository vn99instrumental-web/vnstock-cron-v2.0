# VNStock 6 production task list

Updated: 2026-11-13

## Completed

- [x] Final Gen 6 packages are pinned in an isolated GitHub Actions environment.
- [x] SSI is the explicit reference and primary OHLCV source; FHSC is the market fallback and fundamental source.
- [x] Technical indicators use vnstock_quant.ta.
- [x] Balance sheet, income statement and cash flow feed vnstock_quant.fa ratios and growth.
- [x] Missing factors are excluded and available weights are renormalized.
- [x] Native Git ledger and isolated serving root feed all dashboard tabs.
- [x] The existing n8n workflow keeps five weekday intraday dispatches.
- [x] Intraday fetches only market data and reuses the committed fundamental cache.
- [x] Existing OHLC files use a 14-day correction window instead of refetching 500 days five times per day.
- [x] Daily outcomes and full analytics run separately at 16:15 ICT on weekdays.
- [x] SSI reference and FHSC statements refresh separately at 09:15 ICT on Sundays.
- [x] A failed weekly statement refresh preserves the last successful symbol cache.
- [x] Fundamental cache entries older than 14 days fail closed and are excluded from scoring.

## Operational checks after merge

- [ ] Confirm the first weekly fundamental workflow completes within its 180-minute timeout.
- [ ] Confirm fundamental-factors.json and fundamental-status.json are committed without secret fields.
- [ ] Confirm the next intraday run consumes the refreshed cache and publishes v6.2-quant.
- [ ] Confirm the first daily maintenance run publishes outcomes, IC and analysis and revalidates Vercel.
- [ ] Verify the authenticated Gen 6 dashboard after the first v6.2 production publish.

## Migration and quality gates

- [ ] Build the formal migration inventory and contract report from saved legacy ledgers; the retired legacy APIs cannot be queried live.
- [ ] Remove or archive the RC preview branch in debug.yml.
- [ ] Prevent the manual bridge comparison workflow from overwriting a native dashboard manifest.
- [ ] Accumulate at least 30 forward sessions before using v6.2 as the sole scoring reference.
- [ ] Monitor coverage, IC and missing-factor rates; do not treat missing data as zero.

## Cadence ownership

- n8n owns the five intraday dispatches.
- GitHub Actions owns daily derived-data maintenance and weekly slow-source refresh.
- All writers share vnstock-main-writer so Git commits are serialized.
