# Patch 1.24.0 — candidate/live attrition diagnostics

Date: 2026-07-05

## Problem

The release stored aggregate inference `skip_counts`, published totals and execution-plan status totals, but it could not answer the operational question "where did each candidate or live opportunity terminate?" Repeated hourly/catch-up attempts could be counted more than once, `NO_TRADE`/`BLOCKED_*` plans lacked a stable primary cause, and background candidate gate failures were not combined with live attrition in one integrity-checked report.

This was a confirmed observability and econometric-accounting gap. It did not prove that any existing gate was too strict, but it prevented evidence-based diagnosis of rare recommendations and repeated candidate rejection.

## Solution

- Added one terminal inference outcome for every selected `symbol × event_time`: `SKIPPED`, `PUBLISHED` or `EXISTING_CURRENT_HOUR`.
- Added stable reason codes for publication skips and retry recovery deduplication.
- Added execution-plan attrition evidence in `sizing_snapshot.attrition` with schema, terminal stage, primary/contributing reasons and limiting cap.
- Added candidate training terminal outcomes and grouped quality-gate reasons.
- Added fail-closed denominator, schema, duplicate/conflict and gate/activation consistency checks.
- Added `cam-attrition-report`, `python manage.py attrition-report -- --hours 168`, JSON output and daily-report integration.

## Compatibility

- No Alembic migration.
- No `.env` changes.
- No model artifact schema change and no retraining requirement.
- Existing active model, policy thresholds, risk limits and advisory-only behavior are unchanged.
- Evidence is prospective. Legacy successful inference jobs inside the selected window are excluded and make the aggregate report `BLOCKED`.

## Verification

Baseline: `588 passed, 4 skipped, 61 warnings`.

Red evidence before implementation:

- inference instrumentation regression failed with `KeyError: 'attrition_schema'`;
- aggregate report regression failed collection with `ModuleNotFoundError: No module named 'app.services.attrition'`.

Post-change: `592 passed, 4 skipped, 61 warnings`; Ruff, compileall, pip check, JavaScript syntax and Alembic head checks passed.

PostgreSQL integration and live-user-database report generation were not run because no isolated `TEST_DATABASE_URL` was supplied.

## Operator action

Restart API, worker and trainer, accumulate post-upgrade jobs, then run:

```bash
python manage.py attrition-report -- --hours 168
```

Interpret `reason_counts` as mutually exclusive primary causes. `contributing_reason_counts` is multi-label and cannot be summed as a denominator. Do not lower gates solely because a category is frequent; first confirm a stable prospective pattern and independently validate any proposed policy change.
