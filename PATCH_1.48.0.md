# Patch 1.48.0 — sparse interaction-pool jackknife robustness

## Problem

Release 1.47.0 grouped every `symbol × direction × regime` cell with fewer than five final-holdout trades into one preregistered sparse pool. The pool prevented silent omission and avoided a large family of underpowered individual tests, but its aggregate result could still depend entirely on one profitable tiny cell.

A deterministic reproducer contained three sparse cells with 4, 3 and 3 trades. The pooled mean was `+0.28 R`, while removing the four-trade profitable cell left six trades with `-0.20 R`. The 1.47.0 quality gate accepted the positive pool and had no residual-cell sensitivity evidence.

## Solution

- Raised interaction schema to `symbol-direction-regime-supported-cells-sparse-pool-jackknife-v2`.
- Added immutable nested schema `leave-one-sparse-interaction-cell-out-v1`.
- For every sparse cell, remove the complete cell and recompute residual trade count, mean R, log loss and multiclass Brier from the remaining sparse trades.
- Preserve canonical omitted-cell identity and validate exact residual counts, fractions and weighted arithmetic.
- Require every residual cohort to retain at least five trades and pass the existing policy mean R, log-loss and Brier limits.
- Expose minimum residual support and worst residual metrics in quality-gate evidence.
- Runtime requires the same current evidence before loading an artifact.
- Raised policy metric schema from v24 to v25.

## Configuration and migration

- No Alembic migration.
- No new `.env` variable.
- No EV/RR, spread, holdout, walk-forward, calibration, leverage or risk limit was relaxed.
- Artifacts produced before 1.48.0 require retraining.

## Verification

- Untouched 1.47.0 regression: `6 failed, 1 passed`.
- New regression after implementation: `7 passed`.
- Focused interaction/lifecycle/runtime suite: `35 passed`.
- Full suite: `820 passed, 8 skipped`.
- Ruff, compileall and JavaScript syntax: passed.
- Alembic: one head, `0017_model_artifact_blobs`.

## Limitations

The leave-one-cell-out check establishes that pooled sparse evidence does not depend on any single tiny cell. It does not prove that every individual cell with one to four trades is profitable or sufficiently powered. Multiple harmful tiny cells may still be masked by several profitable tiny cells if every leave-one-out residual remains positive. A hierarchical shrinkage model or substantially more prospective history would be required to estimate each sparse interaction reliably.
