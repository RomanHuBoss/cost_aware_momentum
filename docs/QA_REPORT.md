# QA Report

Release: **1.26.4**

Date: **2026-07-05**  
Scope: **unconditional observed-opportunity policy return path for model promotion**

## Environment

- Python: 3.13.5 in isolated virtual environment `/mnt/data/cam_venv`.
- Project requirement: Python >=3.12.
- Node syntax check available.
- Separate PostgreSQL integration database: not configured.
- Host/global Python was unsuitable for comparable results: `ruff` and `psycopg` were absent and global `pip check` had an unrelated Pillow/MoviePy conflict.

## Baseline before changes

| Check | Result |
|---|---|
| `python -m pip check` | PASSED in isolated venv |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 613 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| package/application version | PASSED: 1.26.3 |

The same commands under host/global Python were recorded separately: compileall and JavaScript syntax passed; `pip check` failed on an unrelated global package conflict, `ruff` was unavailable, and pytest collection failed because `psycopg` was absent.

## Confirmed defect and red evidence

`evaluate_policy_model` aggregated `policy_realized_mean_r`, horizon phases and bootstrap LCB only from hours in which a trade survived selection and overlap filtering. Observed hours where the policy chose `NO TRADE` disappeared from the return path instead of contributing the known strategy return of zero. This conditioned economic inference on the policy's own selected sample and made full phase coverage depend on trade occurrence.

Red command:

```text
python -m pytest -q tests/unit/test_policy_opportunity_path_2026_07_05.py
```

Before implementation: **1 failed** with `KeyError: 'policy_trade_cohorts'`; the original output exposed no full opportunity accounting and reported only traded cohorts.

After implementation: the regression test passes and independently verifies 16 observed cohorts, 8 traded cohorts, 8 zero-return no-trade cohorts, all 8 horizon phases and an unconditional mean of 0.5 rather than the trade-conditional mean of 1.0.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 615 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| application/package version consistency | PASSED: app and package are 1.26.4 |
| static Alembic head check | PASSED: one head, `0014_ui_exposure_ledger` |
| release integrity / manifest | PASSED: 217 eligible files / 217 manifest entries |
| clean ZIP test and re-extraction | PASSED: archive test and clean re-extraction verified |

## Environment-dependent checks

| Check | Result |
|---|---|
| `python manage.py doctor` | FAILED due environment: `.env` absent, default secrets, PostgreSQL tools absent and localhost PostgreSQL unavailable |
| `python manage.py test --require-integration` | NOT RUN as integration evidence: command stopped because neither `TEST_DATABASE_URL` nor `POSTGRES_ADMIN_URL` was configured |

## Warnings

61 warnings are pre-existing Joblib/NumPy and pandas timedelta deprecations. This patch does not add a warning category.

## Release boundary

- Database migration: none.
- Public HTTP API: unchanged.
- `.env` variables: unchanged.
- Advisory-only/read-only Bybit boundary: unchanged.
- Policy metric schema: `...cohort-v16` → `...cohort-v17`.
- Policy uncertainty schema: `all-horizon-phases-circular-moving-block-v2` → `observed-opportunity-zero-return-all-horizon-phases-circular-moving-block-v3`.
- Already active artifacts remain runnable. Inactive candidates with legacy quality evidence require retraining and new governed experiment evidence before normal activation.
