# QA Report

Release: **1.26.5**

Date: **2026-07-05**
Scope: **observed experiment-period support and legacy evidence invalidation**

## Environment

- Python: 3.13.5 in isolated virtual environment `/mnt/data/cam_iter_venv`.
- Project requirement: Python >=3.12.
- Node syntax check available.
- Separate PostgreSQL integration database: not configured.
- Host/global Python was unsuitable for comparable results: `ruff` and `psycopg` were absent and global `pip check` had an unrelated Pillow/MoviePy conflict.

## Baseline before changes

| Check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED in isolated venv |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 615 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| package/application version | PASSED: 1.26.4 |

The same commands under host/global Python were recorded separately: compileall and JavaScript syntax passed; `pip check` failed on an unrelated global package conflict, `ruff` was unavailable, and pytest collection stopped with 33 import errors because `psycopg` was absent.

## Confirmed defect and red evidence

`policy_backtest` generated experiment timestamps with a continuous calendar `date_range` from the earliest decision to the latest exit. Two valid decision cohorts 100 hours apart therefore produced 102 period rows, including 98 unavailable hours represented as zero return. Those rows entered minimum-period, Sharpe, DSR, PBO and dependence calculations.

Red command:

```text
python -m pytest -q tests/unit/test_experiment_observed_period_path_2026_07_05.py
```

Before implementation: **3 failed**:

1. 102 timestamps were emitted instead of four covered timestamps;
2. legacy `hourly-realized-capital-return-path-v1` evidence was accepted;
3. invalid evidence propagated `ValueError` through the promotion gate.

After implementation: **3 passed**.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 618 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| application/package version consistency | PASSED: app and package are 1.26.5 |
| static Alembic head check | PASSED: one head, `0014_ui_exposure_ledger` |
| release integrity / manifest | PASSED: 220 files checked, 220 manifest entries |
| clean ZIP test and re-extraction | PASSED: one root directory; `unzip -t` clean; re-extracted manifest verified |

## Environment-dependent checks

| Check | Result |
|---|---|
| `python manage.py doctor` | FAILED as expected for this sandbox: `.env` absent, default secrets unresolved, PostgreSQL tools absent, service unreachable |
| `python manage.py test --require-integration` | NOT RUN: neither `POSTGRES_ADMIN_URL` nor `TEST_DATABASE_URL` is configured |

## Warnings

61 warnings are pre-existing Joblib/NumPy and pandas timedelta deprecations. This patch does not add a warning category.

## Release boundary

- Database migration: none.
- Public HTTP API: unchanged.
- `.env` variables: unchanged.
- Trading/risk/model-quality thresholds: unchanged.
- Advisory-only/read-only Bybit boundary: unchanged.
- Experiment period-return schema: `hourly-realized-capital-return-path-v1` → `observed-opportunity-covered-hourly-capital-return-path-v2`.
- Active artifacts remain runnable. Existing experiment families with successful v1 trials require rerun before normal activation.
