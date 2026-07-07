# Patch 1.42.0 — policy-actionable calibration integrity

Date: 2026-07-07

## Problem

The final holdout first chooses one LONG/SHORT direction per market opportunity and then applies economic actionability and single-active-trade overlap filters. Release 1.41.0 correctly gated calibration of the selected direction, but it still measured that calibration across all selected opportunities, including the much larger set that policy ultimately rejected as `NO TRADE`.

A deterministic reproducer showed the practical selection bias: 130 accurately classified non-actionable observations kept selected-direction log loss below the configured 1.20 limit while the 20 observations that actually became trades had log loss above 4 and multiclass Brier above 1.5. The activation gate therefore could approve a model whose rare published recommendations were materially overconfident.

The artifact contract also did not require calibration evidence for the actual post-actionability/post-overlap trade cohort or bind its row count to `policy_trades`.

## Correction

- `evaluate_policy_model()` now computes a separate calibration reference from the exact rows remaining after actionability and overlap filtering.
- Persisted fields are `policy_actionable_calibration_schema`, `policy_actionable_calibration_rows`, `policy_actionable_log_loss` and `policy_actionable_multiclass_brier`.
- The actionable cohort schema is `actionable-policy-trades-final-holdout-v1`.
- The quality gate applies the unchanged absolute log-loss and multiclass-Brier limits to this cohort.
- Actionable calibration rows must equal `policy_trades` exactly.
- Missing, non-finite, negative or contradictory evidence fails closed with dedicated reason codes.
- Runtime validates the v19 policy metric schema and actionable evidence before loading an artifact.
- Legacy artifacts without this evidence are rejected and require retraining.

## Compatibility

No database migration or `.env` change is required. Policy metric schema is now `decision-close-zone-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v19`; this is an immutable artifact contract change.

No holdout, walk-forward, trade-rate, spread, EV/RR, fee, funding, leverage, sizing or risk threshold was relaxed.

## Verification

Baseline 1.41.0:

- Full suite: `768 passed, 8 skipped`.
- New regression suite on untouched code: `6 failed, 1 passed`.

Release 1.42.0:

- New regression suite: `7 passed`.
- Full suite: `775 passed, 8 skipped`.
- Ruff, compileall and JavaScript syntax: passed.
- Alembic: one unchanged head, `0017_model_artifact_blobs`.

PostgreSQL integration tests were skipped because no isolated PostgreSQL test database was configured. The operator database was not accessed.

## Limitations

Actionable calibration is estimated from a finite final holdout and does not establish live profitability. It does not yet test calibration stability by symbol, market regime or walk-forward fold. Exact historical fills, queue position, partial fills, sub-hour execution and operator latency remain unavailable.
