# SSI independent scoring on shared SSI/FHSC data — transition record

Date: 2026-11-25
Status: deployed transition; superseded as target architecture

## Correction

The first implementation reused Gen 6 materialized feature rows. It is independent at the scoring layer, but it is not independent at the input-calculation layer and therefore does not satisfy the final SSI standalone requirement.

The canonical decision is now:

- [SSI_STANDALONE_SOURCE_BOUNDARY_20261125.md](SSI_STANDALONE_SOURCE_BOUNDARY_20261125.md)
- [SSI_STANDALONE_PENDING_TASKS_20261125.md](SSI_STANDALONE_PENDING_TASKS_20261125.md)

Gen 6 and SSI may share the same provider facts from SSI and FHSC only at the raw/immutable boundary. They must calculate technical features, BCTC ratios/growth/cash-flow, signals, scores and decisions independently.

## What the deployed transition actually proves

- `scripts/ssi_independent_pipeline.py` does not import a Gen 6 scorer.
- It ignores input `s_*`, `score_trade`, `score_hold` and `decision` fields and recomputes the 17 signals, factors and scores.
- It publishes separate SSI serving, ledger, outcomes, IC and `/ssi/*` dashboard artifacts.

## What it does not prove

- The pipeline reads `output/serving/vnstock6/current/today` and `output/history/vnstock6/predictions`.
- Fundamental inputs were calculated by `scripts/vnstock6_quant.py` using `vnstock_quant.fa` before SSI consumed them.
- The SSI workflow is triggered by a successful Gen 6 production workflow.

Accordingly, the current deployment is labelled `transitional_score_independent`, not `standalone`.

## Verified transition snapshot

For source date 2026-11-23, the repository contains 100/100 scored symbols, 7 source dates / 700 predictions, D+3 `n=400` and D+5 `n=200`. D+10 is pending until ten future trading sessions exist. These facts remain valid for the transition artifact and are not an investment recommendation.
