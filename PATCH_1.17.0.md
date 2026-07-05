# Patch 1.17.0 — production drift monitoring

## Problem

Active production models had no version-scoped monitoring against their own final-holdout distribution. The system could detect stale market inputs and reject incompatible artifacts, but it did not quantify feature/probability drift, missingness, inference coverage, calibration degradation or changes in recommendation actionability after activation.

A naive monitor would also be unsafe if it compared production outcomes with a calibration baseline built from both hypothetical LONG and SHORT rows while production outcomes exist only for the selected direction. That cohort mismatch would create false calibration alerts.

## Solution

- Persist an immutable drift reference in every candidate artifact and registry metrics.
- Build feature and probability histograms from the untouched final holdout using fixed quantile bins.
- Build calibration baseline only from the policy-selected direction for each symbol/timestamp.
- Persist baseline actionability density and policy RR/EV thresholds.
- Store both LONG and SHORT probability vectors in every published signal feature snapshot.
- Run an hourly monitor for the active model version only.
- Calculate coverage, missingness, feature/probability PSI, selected-direction log-loss/Brier deltas and actionability-rate delta.
- Treat insufficient evidence, failed inference jobs and invalid coverage accounting as `BLOCKED`.
- Surface `CRITICAL/BLOCKED` as `DEGRADED` worker heartbeat status.
- Keep model governance manual/guarded: the monitor never activates, deactivates, rolls back or changes a model and never weakens promotion or risk gates.

## Contracts

- Drift reference schema: `final-holdout-feature-probability-selected-calibration-reference-v2`.
- Calibration cohort: `selected-direction-final-holdout-v1`.
- Directional signal probability snapshot: `both-directional-probabilities-v1`.
- Drift report: `production-drift-report-v1`.

Artifacts created before 1.17.0 do not contain the mandatory reference and are rejected fail-closed by runtime and activation checks. Retraining is required.

## Configuration

New optional settings with safe defaults:

```env
DRIFT_MONITOR_ENABLED=true
DRIFT_WINDOW_HOURS=168
DRIFT_MIN_FEATURE_OBSERVATIONS=48
DRIFT_MIN_OUTCOME_OBSERVATIONS=30
DRIFT_MIN_COVERAGE_RATE=0.80
DRIFT_MAX_MISSING_RATE=0.02
DRIFT_WARNING_PSI=0.10
DRIFT_CRITICAL_PSI=0.25
DRIFT_MAX_LOG_LOSS_DELTA=0.10
DRIFT_MAX_BRIER_DELTA=0.05
DRIFT_MAX_ACTIONABILITY_RATE_DELTA=0.20
```

Invalid threshold ordering, rates or sample sizes fail configuration validation.

## Database and compatibility

- No Alembic migration.
- Existing `MarketSignal.feature_snapshot`, `ModelRegistry.metrics`, `JobRun.details` and `ServiceHeartbeat.details` JSON fields store the new evidence.
- Active artifacts from 1.16.0 must be replaced by a newly trained 1.17.0 candidate.
- No order-create, amend or cancel capability was added.

## Commands

```bash
python manage.py drift-report
python manage.py report -- --hours 24 --selection-days 90
```

Default drift output: `reports/production_drift.json`.

## Validation

- Baseline: 531 passed, 4 skipped.
- Post-change: 540 passed, 4 skipped before final release-document checks.
- New red evidence: the new test module failed on 1.16.0 with `ModuleNotFoundError: No module named 'app.ml.drift'`.
- PostgreSQL integration tests remain skipped without an isolated `TEST_DATABASE_URL`.

## Limitations

- PSI is a univariate distribution diagnostic and does not establish causal degradation.
- Calibration monitoring waits for resolved outcomes and therefore lags current inference.
- Thresholds are fixed operational defaults, not statistically optimized control limits.
- No automatic rollback/deactivation is performed.
- Monitoring cannot prove profitability or distinguish all forms of regime change from data-quality change.
