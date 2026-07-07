# Patch 1.49.0 — terminal inference coverage and actionability-density accounting

## Problem

Hourly inference already records exactly one terminal `symbol_outcomes` entry for every selected symbol. A terminal outcome may be `PUBLISHED`, `EXISTING_CURRENT_HOUR` or an intentional `SKIPPED` result such as `spread_above_execution_limit`, `insufficient_candle_history`, `NO_TRADE` economics or stale data.

Release 1.48.0 nevertheless treated only `published + existing_current_hour` as completed coverage in two places:

1. `should_retry_incomplete_inference()` retried a successful sparse inference up to five times whenever most symbols correctly produced no recommendation.
2. Production drift divided published recommendations by the universe and called that processing coverage, while actionability density was calculated only inside the already-published signal list. Sparse but completely processed inference could therefore be simultaneously reported as low coverage and 100% actionable.

The production drift reference also used the wider pre-overlap actionable-candidate rate, while production telemetry contains final published policy trades after overlap filtering.

## Solution

- Use `symbol_outcome_count` as the authoritative inference processing-coverage count.
- Retry only when some selected symbols lack a terminal outcome; old job details without the new field retain the legacy fallback.
- Separate three immutable counts in drift report v4:
  - expected symbol opportunities;
  - processed terminal outcomes;
  - actionable published/existing signals.
- Calculate coverage as `processed / expected`.
- Calculate actionability density as `actionable / expected`, never as the fraction of already-published signals.
- Bind the reference actionability rate to final `policy_trades / policy_candidates` rather than pre-overlap actionable candidates.
- Add actionability cohort schema `published-policy-trades-per-symbol-opportunity-v1` and raise the production drift reference schema to v4.
- Missing or malformed terminal coverage evidence remains fail-closed `BLOCKED`; genuine actionability drift remains capable of producing `CRITICAL` quarantine.

## Configuration and migration

- No Alembic migration.
- No new `.env` variable.
- Existing EV/RR, calibration, holdout, walk-forward, spread, leverage and risk limits are unchanged.
- Pre-1.49 model artifacts contain drift reference v3 and require retraining before normal runtime loading.

## Verification

- Untouched 1.48.0 regression: `7 failed, 1 passed`.
- New regression after implementation: `8 passed`.
- Focused inference/drift compatibility: `22 passed`.
- Full suite: `828 passed, 8 skipped`.
- Ruff, compileall and JavaScript syntax: passed.
- Alembic: one head, `0017_model_artifact_blobs`.

## Limitations

Feature and probability PSI are still calculated from stored published signals rather than a separate immutable ledger of every evaluated no-trade opportunity. This release fixes processing coverage and actionability-density denominators, but does not yet implement all-opportunity production feature/probability telemetry or symbol/regime-conditional drift.
