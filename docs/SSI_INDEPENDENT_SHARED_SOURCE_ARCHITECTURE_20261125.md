# SSI independent scoring on the shared SSI/FHSC feature layer

Date: 2026-11-25
Status: implemented, pushed and production-deployed

## Decision

SSI scoring reuses the same materialized source and feature layer as Gen 6 because both products use the same providers:

- SSI supplies reference data, OHLCV, session statistics and primary foreign flow.
- FHSC supplies fundamentals, order book, foreign fallback and post-market slow-flow datasets.

Only the scoring calculation is independent. `scripts/ssi_independent_pipeline.py` does not import a Gen 6 scoring module and deliberately ignores every `s_*`, `score_trade`, `score_hold` and `decision` field present in the shared input rows. It recomputes the 17 signals, factors, scores and decisions from the raw/materialized feature fields.

This corrects the earlier assumption that the SSI track needed a separate provider ingestion path or exact parity with a frozen legacy artifact. Separate ingestion would duplicate calls, cadence logic and caches without improving calculation independence.

## Runtime flow

1. Gen 6 source workflows materialize SSI/FHSC feature rows and OHLCV.
2. `.github/workflows/ssi_independent_production.yml` starts only after a successful `VNStock 6 native production` run, or by manual dispatch.
3. The independent test suite proves that changing Gen 6 signals/scores/decisions does not alter SSI output.
4. The independent calculator builds its own serving tree, prediction ledger, outcomes and IC.
5. The workflow commits only SSI artifacts and revalidates the Vercel dashboard.

The workflow dependency is a data-readiness dependency, not a scoring-engine dependency.

## Artifacts

- Configuration: `config/ssi_independent.json`
- Calculator: `scripts/ssi_independent_pipeline.py`
- Tests: `tests/test_ssi_independent_pipeline.py`
- Serving: `output/serving/ssi/current/`
- Ledger: `output/history/ssi-independent/predictions/`
- Web projection: `web/data/ssi-independent-dashboard.json`
- Dashboard routes: `/ssi`, `/ssi/buy`, `/ssi/today`, `/ssi/phan-tich`, `/ssi/history`, `/ssi/ic`

## Missing-data and outcome policy

- Missing optional source signals remain `null` and are excluded with weight renormalization. They are never converted to neutral zeroes.
- Every latest-universe symbol with at least the source gate is scored; signal coverage is displayed explicitly.
- D+3, D+5 and D+10 outcomes are calculated only from later observed trading sessions.
- D+10 remains pending until ten future sessions exist. No future return or IC value is fabricated.

## Current verified snapshot

For source date 2026-11-23:

- 100/100 symbols scored.
- 43 BUY or STRONG BUY; 16 SELL or STRONG SELL.
- Coverage distribution: 41 rows at 17/17, 36 at 16/17, 21 at 15/17 and 2 at 14/17.
- History: 7 source dates and 700 symbol-date predictions.
- Outcome availability: D+3 `n=400`, D+5 `n=200`, D+10 pending.

These values describe the available repository snapshot, not an investment recommendation.
