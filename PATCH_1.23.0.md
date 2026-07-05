# Patch 1.23.0 — maturity-aware production calibration drift

Date: 2026-07-05

## Problem

`SignalOutcome` can be written before the configured horizon ends when TP or SL is touched. A TIMEOUT outcome cannot exist until the full horizon has elapsed. Release 1.22.0 joined every already-resolved outcome in the monitoring window, so early TP/SL rows from immature signals entered production calibration while equivalent not-yet-resolved TIMEOUT rows were absent.

This is right-censoring, not genuine calibration evidence. It could create a false log-loss/Brier deterioration and mark the worker heartbeat `DEGRADED`.

## Solution

- Partition active-version signals by full-horizon maturity using `event_time + horizon_hours <= report time`.
- Keep feature/probability PSI and actionability diagnostics on the complete monitoring window.
- Restrict calibration outcomes to mature signals only.
- Exclude and count early resolved outcomes from immature signals.
- Require exactly one outcome for every mature signal; unresolved, duplicate or invalid maturity evidence blocks calibration fail-closed.
- Add report contract `production-drift-report-v2` and outcome cohort `full-horizon-mature-signal-outcomes-v1`.

## Compatibility

- No database migration; Alembic head remains `0014_ui_exposure_ledger`.
- No new or changed `.env` variable.
- No artifact schema change and no model retraining requirement.
- No API endpoint or advisory-only boundary change.
- `reports/production_drift.json` gains `outcome_coverage` and uses report schema v2.

## Verification

Baseline before changes:

- `python -m pytest -q`: `586 passed, 4 skipped, 61 warnings`.
- Ruff, compileall, `pip check`, Node syntax and Alembic head passed.

Red evidence:

- immature early outcome was counted: expected 1 mature calibration observation, actual 2;
- one unresolved mature signal produced `CRITICAL` rather than fail-closed `BLOCKED`.

Post-change focused tests:

- `10 passed` across the new regressions and the existing production-drift module.

Post-change full suite:

- `588 passed, 4 skipped, 61 warnings`.
- Ruff, compileall, `pip check`, Node syntax and Alembic head passed.

## Limitations

This is deterministic full-horizon filtering. It does not implement a survival model, inverse-probability-of-censoring weighting, multivariate drift tests, adaptive control limits or automatic rollback. Monitoring remains observational with `automatic_model_action=none`.
