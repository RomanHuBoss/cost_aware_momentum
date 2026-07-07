# Patch 1.41.0 — policy-selected calibration integrity

Date: 2026-07-07

## Problem

The final holdout contains two counterfactual rows per market opportunity: LONG and SHORT. The policy then selects at most one direction from that pair. Training already computed log loss and multiclass Brier for the selected direction, but the activation quality gate only enforced the global metrics averaged across both directions.

This allowed a candidate to be well calibrated on the unselected side while being materially overconfident on the direction that would actually be published. The immutable production-drift reference also accepted the selected-cohort schema without requiring explicit selected-direction metrics, so an all-direction matrix could be mislabeled as selected evidence.

The gate additionally did not verify the exact arithmetic relationship among directional holdout rows, policy opportunities and selected calibration rows. Internally contradictory evidence could therefore pass normal activation.

## Correction

- Production-drift reference schema is now `final-holdout-feature-probability-selected-calibration-reference-v3`.
- Selected calibration cohort schema is now `selected-direction-final-holdout-v2`.
- Building a selected-cohort reference requires an explicit `rows`, `log_loss` and `multiclass_brier` mapping; implicit calculation from all-direction probabilities is rejected.
- The quality gate applies the existing absolute log-loss and multiclass-Brier limits to selected-direction calibration.
- The gate requires `holdout_rows == 2 × policy_candidates`.
- The gate requires `selected_calibration_rows == policy_candidates`.
- The immutable drift reference row count must equal the candidate final-holdout directional row count.
- Missing, non-finite, malformed or inconsistent selected evidence fails closed with dedicated reason codes.

## Compatibility

No database migration or `.env` change is required.

The drift-reference and selected-calibration schemas are immutable artifact contracts. Artifacts produced before 1.41.0 do not provide the strengthened evidence and are intentionally rejected by runtime validation. Train a new candidate and let it pass the unchanged temporal, ML, policy and experiment-promotion gates.

No risk, EV/RR, spread, holdout, walk-forward or actionability threshold was relaxed.

## Verification

Baseline 1.40.0:

- Full suite: `762 passed, 8 skipped`.
- New regression suite: `6 failed` for the expected missing guards.

Release 1.41.0:

- New regression suite: `6 passed`.
- Full suite: `768 passed, 8 skipped`.
- Ruff, compileall and JavaScript syntax: passed.
- Alembic: one unchanged head, `0017_model_artifact_blobs`.

PostgreSQL integration tests were skipped because no isolated PostgreSQL test database was configured. The operator database was not accessed.

## Limitations

Selected-direction calibration is still estimated from the finite final holdout and does not prove live profitability. Historical entry remains a constrained next-hour-open proxy; queue position, partial fills, sub-hour path and operator latency remain incompletely modeled.
