# Patch 1.47.0 — policy interaction robustness

## Problem

Final-holdout evidence in 1.46.0 separately checked aggregate actionable calibration, symbols, dependence clusters, market regimes and LONG/SHORT directions. Those marginal checks did not detect a harmful `symbol × direction × regime` interaction when profitable observations in the other cells kept every marginal average positive.

A deterministic reproducer produced:

- aggregate actionable mean: `+0.70 R`;
- minimum per-symbol mean: `+0.40 R`;
- minimum per-direction mean: `+0.40 R`;
- minimum per-regime mean: `+0.40 R`;
- `BTCUSDT × LONG × UPTREND`: `-0.20 R`.

## Solution

- Added immutable schema `symbol-direction-regime-supported-cells-sparse-pool-v1`.
- Exact cells are constructed only after policy direction selection, EV/RR actionability and overlap filtering.
- Cells with at least five trades are evaluated separately for realized trade mean R, log loss and multiclass Brier.
- Cells below five trades are combined into one deterministic sparse pool. This avoids silently dropping rare interactions and avoids treating many tiny cells as separate underpowered tests.
- A non-empty sparse pool must itself contain at least five total trades and pass the same economics/calibration limits.
- Cell keys, canonical ordering, counts, fractions, calibration rows, weighted sparse-pool metrics and extrema are validated fail-closed.
- Interaction symbol, direction and regime sets must exactly match the existing marginal evidence.
- Runtime requires current interaction evidence before loading an artifact.
- Policy metric schema increased from v23 to v24.

## Configuration and migration

- No Alembic migration.
- No new `.env` variable.
- Existing thresholds are reused; no EV/RR, calibration, holdout, walk-forward, spread or risk limit was relaxed.
- Artifacts produced before 1.47.0 require retraining.

## Verification

- Untouched 1.46.0 original regression: `6 failed, 1 passed`.
- Final interaction regression: `9 passed`.
- Focused lifecycle/runtime compatibility: `26 passed`.
- Full suite: `813 passed, 8 skipped`.
- Ruff, compileall and JavaScript syntax: passed.
- Alembic: one head, `0017_model_artifact_blobs`.

## Limitations

The sparse pool is a conservative compromise, not a formal causal or hierarchical model. It does not identify which individual cell is harmful when all constituent cells are below five trades. Five observations are only a minimum safety floor. Full retraining and forward evaluation on the operator PostgreSQL/Bybit environment were not performed.
