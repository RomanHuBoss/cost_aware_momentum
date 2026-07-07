# Patch 1.50.0 — all-opportunity production drift telemetry

## Problem

Production feature and probability PSI used `advisory.market_signals`. A row reached that table only after executable spread, funding, directional economics, EV/RR and publication filters. Therefore the monitored cohort was conditioned on the policy accepting an opportunity. When recommendations were rare, a material shift in features or raw model probabilities among rejected opportunities could remain invisible or produce too little evidence.

This was a confirmed gap, not a claim that the strategy is profitable or that every loss has one cause.

## Solution

- Added `model.model_inference_observations` for the first successful artifact evaluation of each `(model_version, symbol, event_time)`.
- Persisted exact feature and LONG/SHORT probability snapshots before spread/funding/EV/RR filters.
- Bound each row to model, calibration and feature-schema versions.
- Added a transaction-scoped advisory lock plus a unique constraint for retry/concurrency idempotency.
- Added PostgreSQL checks and an immutable UPDATE/DELETE trigger.
- Switched feature/probability drift to this ledger; published signals remain the realized-outcome cohort for calibration.
- Invalid observation version/schema evidence blocks the report fail-closed.

## Migration and compatibility

- New Alembic head: `0018_inference_observations`.
- Run `python manage.py migrate` before restarting API, worker and trainer.
- No `.env`, API, UI, artifact schema, EV/RR, spread, leverage, risk or activation-threshold change.
- Existing active artifacts remain loadable. The ledger is prospective; pre-upgrade rejected opportunities cannot be reconstructed.
- Downgrade removes the ledger and its trigger and therefore discards its telemetry rows.

## Verification

- Red: the new test failed during collection on unmodified 1.49.1 because `ModelInferenceObservation` did not exist.
- Green targeted tests: model/table immutability contract, artifact-bound idempotent persistence, and all-opportunity PSI passed.
- Full suite: `832 passed, 8 skipped`.
- Ruff, compileall, pip dependency check and `node --check web/js/app.js` passed.
- Live PostgreSQL migration/integration was not run because no isolated `TEST_DATABASE_URL` was available.
