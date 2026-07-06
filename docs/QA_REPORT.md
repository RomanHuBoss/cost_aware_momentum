# QA Report

Release: **1.27.0**

Date: **2026-07-06**
Scope: **critical production-drift publication interlock**

## Environment

- Python: 3.13.5 in isolated virtual environment `/mnt/data/cam_venv`.
- Project requirement: Python >=3.12.
- Node syntax check available.
- Separate PostgreSQL integration database: not configured.
- Host/global Python was unsuitable: `ruff`/`psycopg` were absent and global `pip check` had an unrelated MoviePy/Pillow conflict.

## Baseline before changes

| Check | Result |
|---|---|
| input ZIP SHA-256 | `d5e3e857ef4adb0e946a4ba3b3aacdf379b493fa1c0b03566ef3ebdfc0957436` |
| source version | 1.26.7 |
| source inventory | 225 files; 94 production Python, 83 test Python, 10 docs; 14 migration revisions; head `0014_ui_exposure_ledger` |
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED in isolated venv |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 627 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |

## Confirmed gap and red evidence

`app/services/drift_monitor.py` produced `CRITICAL`, but `app/workers/runner.py::model_heartbeat_status` only degraded heartbeat. The loop published inference before running drift, `publish_hourly_signals` had no interlock, and execution/acceptance paths did not consult drift evidence. A critically degraded active artifact could therefore continue issuing new advisory decisions and an older actionable plan could still be accepted.

Original red command:

```text
python -m pytest -q tests/unit/test_critical_drift_interlock_2026_07_06.py
```

Before production implementation: collection failed because `PRODUCTION_DRIFT_PUBLICATION_GUARD_SCHEMA` and the guard did not exist. After implementation: **4 passed**.

Acceptance red command:

```text
python -m pytest -q tests/unit/test_execution_acceptance_safety.py::test_acceptance_rejects_actionable_plan_after_critical_drift
```

First run: **1 failed**, endpoint returned HTTP 200 instead of 409 because the drift conflict was overwritten by later plan-contract validation. After preserving the pre-existing conflict: **1 passed**.

## Added/extended regression coverage

- Current-version `CRITICAL` latches quarantine across later `BLOCKED` reports and worker restarts.
- Disabling new drift-monitor jobs does not clear already persisted critical quarantine.
- Reactivating the same immutable artifact version does not clear its historical critical latch.
- Previous-version critical evidence does not quarantine a newly activated version.
- Stale runtime/signal version mismatching current active registry fails closed.
- Signal publication stops before market/profile queries and records per-symbol attrition.
- Hourly decision order evaluates drift before inference.
- New/recalculated execution plans become `NO_TRADE` with persisted guard evidence.
- Acceptance of an old actionable plan returns 409 and supersedes the plan.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 636 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| application/package version consistency | PASSED: 1.27.0 |
| Alembic heads | PASSED: one head, `0014_ui_exposure_ledger` |
| release manifest | PASSED: 227 release files regenerated and verified |
| clean ZIP/re-extraction | PASSED: one root directory, `unzip -t` clean, re-extracted manifest and forbidden-artifact scan clean |

## Environment-dependent checks

| Check | Result |
|---|---|
| `python manage.py doctor` | FAILED: `.env` absent, default secrets unresolved, PostgreSQL client tools/server unavailable in this container |
| `python manage.py test --require-integration` | FAILED preflight: command exited 1 because neither `POSTGRES_ADMIN_URL` nor `TEST_DATABASE_URL` is configured; integration tests were not executed |

## Warnings

62 warnings are existing Joblib/NumPy and pandas timedelta deprecations. No new warning category was introduced.

## Release boundary

- Database migration: none.
- Public HTTP request/response schema: unchanged.
- `.env` variables: unchanged.
- Model feature/label/runtime artifact schemas: unchanged.
- Recommendation/risk/quality/promotion thresholds: unchanged.
- New safety invariant: successful persisted `CRITICAL` drift for the exact active version quarantines new signals and plans until another version is activated.
- Existing `BLOCKED` warm-up/incomplete-evidence diagnostics remain heartbeat-degrading but do not latch publication, preventing self-blocking evidence collection.
