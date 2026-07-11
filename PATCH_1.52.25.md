# PATCH 1.52.25 — transient-inference-retry

Date: 2026-07-11  
Scope: `transient-inference-retry`  
Version type: patch

## Summary

This patch fixes a recovery defect in the hourly recommendation path. A symbol that produced a complete `SKIPPED` outcome because required market data had not arrived yet was treated as permanently complete for that decision hour. The market-close job could subsequently acquire the missing evidence, but `hourly_inference` would return `already_completed` and never re-evaluate it.

Release 1.52.25 keeps explicit data-availability skips retryable on the existing cooldown, for at most five retries, and only while the immutable decision publication window remains open. It does not retry spread, entry-zone, model, drift, or economics rejects.

## Confirmed defect

Type: CONFIRMED DEFECT  
Severity: high  
File/function: `app/workers/runner.py::should_retry_incomplete_inference`

- Actual behavior: `symbol_outcome_count == symbols_total` made every `SKIPPED` result final, including `missing_decision_candle` and `incomplete_market_context`.
- Expected behavior: processing coverage remains complete, but an explicit transient data-availability outcome remains bounded-retryable while the original decision can still be published.
- Operational impact: a short exchange/API/database delay at the first hourly pass could suppress a recommendation for the entire hour. Repeated delays could produce a prolonged empty recommendation surface even though later market-data refreshes succeeded.
- Why tests missed it: existing tests distinguished recommendation count from terminal processing coverage, but did not distinguish permanent policy outcomes from recoverable data-availability outcomes.

## Fix

- Added an explicit allowlist of transient market-data reason codes.
- Preserved the existing missing-terminal-outcome compatibility behavior.
- Preserved the existing cooldown, `inference_retry_count`, maximum of five retries, and publication-window stale check.
- Kept spread, entry-zone, model, drift, economics, and safety-interlock reasons terminal.
- Added operator/runbook guidance for distinguishing delayed data from intentional no-trade outcomes.

## Red → green evidence

Red command on unpatched 1.52.24 after adding the regression:

```bash
python -m pytest -q \
  tests/unit/test_inference_retry.py::test_complete_hourly_inference_retries_transient_market_data_skip
```

Red result:

```text
FAILED test_complete_hourly_inference_retries_transient_market_data_skip
AssertionError: assert False
1 failed in 1.60s
```

Green result after the fix:

```text
1 passed in 1.28s
```

Related subset:

```text
6 passed in 1.23s
```

Full non-integration suite:

```text
917 passed, 8 skipped
```

## Compatibility and deployment

- Alembic migration: none; head remains `0018_inference_observations`.
- `.env`: no variable added, removed, renamed, or reinterpreted.
- API/JSON schema: unchanged.
- Model artifact and training/promotion contracts: unchanged.
- Strategy, risk, spread, EV/RR, freshness, and publication thresholds: unchanged.
- Bybit endpoint set: unchanged and read-only.
- Operator action: deploy the archive and restart the worker. Restarting API/trainer is safe but not required by this code path.

This patch proves the recovery contract in unit tests. It does not prove that this defect was the only cause in a particular deployment without that deployment's PostgreSQL `JobRun` evidence and logs.
