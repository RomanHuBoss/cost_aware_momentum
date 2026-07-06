# Patch 1.35.1 — current-entry conditional TIMEOUT repricing

Date: 2026-07-06

## Problem

The trained conditional TIMEOUT estimator produces a direction-signed gross return in stop-risk units (`timeout_return_r`). Signal publication correctly converted that `R` estimate into an absolute return using the signal-reference TP/SL geometry. Execution-plan construction and acceptance could later use a different current ask/bid or depth VWAP, but reused the old absolute percentage return.

That changed the learned `R` semantics after repricing. For an adverse LONG move from 100 to 100.4 with stop 98 and `timeout_return_r=-0.5`, the stale rate remained `-1.0%`; the current stop-risk projection is approximately `-1.1952%`. In a regression case the stale calculation produced `0.0526R`, above the configured `0.05R` gate, while the correct current-entry calculation produced `0.0235R` and must be blocked.

## Correction

- `signal_timeout_return_rate` accepts the current execution entry.
- When immutable `timeout_return_r` exists, it validates current LONG/SHORT geometry, recomputes gross stop and TP distances, clamps the estimate to current `[-1R, TP-support]`, and returns the current-entry absolute TIMEOUT rate.
- Plan creation passes the converged current bid/ask or depth VWAP.
- Acceptance passes the fresh executable price.
- Legacy signals without `timeout_return_r` keep their stored absolute rate or configured fallback.
- Invalid/non-finite `R` and invalid current geometry remain fail-closed.
- Plan evidence schema is `tp-sl-timeout-current-entry-r-v2`.

## Compatibility

- Database migration: none.
- New `.env` variables: none.
- Model artifact, feature, label and class schemas: unchanged.
- Active artifacts do not require retraining.
- API remains backward compatible; existing plan snapshots retain their historical schema.
- Advisory-only and read-only Bybit boundaries are unchanged.

## Validation

Baseline 1.35.0:

- `699 passed, 7 skipped, 62 warnings`;
- Ruff, compileall, pip check, JavaScript syntax and Alembic head passed.

Release 1.35.1:

- `704 passed, 7 skipped, 62 warnings`;
- 58 focused conditional-TIMEOUT/execution tests passed;
- Ruff, compileall, pip check, JavaScript syntax and Alembic head `0016_universe_replay_asof` passed.

PostgreSQL integration tests were skipped because no isolated `TEST_DATABASE_URL` was available.

## Operator action

Replace the application and restart API/inference worker processes. No migration, `.env` change or active-model retraining is required. Existing plans are immutable; recalculate a plan before acceptance so it receives v2 current-entry economics.
