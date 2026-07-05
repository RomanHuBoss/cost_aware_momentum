# QA Report

Release: **1.26.6**

Date: **2026-07-05**
Scope: **hourly mark-to-market experiment return path**

## Environment

- Python: 3.13.5 in isolated virtual environment `/mnt/data/cam_1265_venv`.
- Project requirement: Python >=3.12.
- Node syntax check available.
- Separate PostgreSQL integration database: not configured.
- Host/global Python was unsuitable for comparable results: `ruff` and `psycopg` were absent and global `pip check` had an unrelated Pillow/MoviePy conflict.

## Baseline before changes

| Check | Result |
|---|---|
| input ZIP SHA-256 | `6a7b5bb89053eb519c3afc023a6e3c3d526221e5261da48070b8f9a3a72f7357` |
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED in isolated venv |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 618 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| package/application version | PASSED: 1.26.5 |

Under host/global Python, compileall and JavaScript syntax passed; `pip check` failed on an unrelated global package conflict, `ruff` was unavailable, and pytest collection stopped with 34 import errors because `psycopg` was absent.

## Confirmed defect and red evidence

`_simulate_capital_sleeves_evidence` posted the complete trade P&L only at `exit_time`. For a two-hour trade with cumulative returns `0%, -20%, +1%` and a 50% horizon sleeve, the old code emitted portfolio period returns `[0.0, 0.0, 0.005]` and `max_drawdown=0`. The economically consistent path is `[0.0, -0.10, 0.116666…]`, ending at the same +0.5% portfolio result but with a -10% drawdown.

Red command:

```text
python -m pytest -q tests/unit/test_experiment_overfitting_governance_2026_07_05.py::test_capital_sleeve_evidence_marks_intrahorizon_drawdown_before_profitable_exit
```

Before implementation: **1 failed** with the exit-only values above.

After implementation: **1 passed**.

## Added/extended regression coverage

- Intrahorizon drawdown is recognized before a profitable exit and reconciles to terminal sleeve capital.
- Experiment evidence fails closed when cumulative hourly MTM metadata is missing.
- Exit-realized v2 period evidence is rejected under the v3 schema.
- Existing dataset and split tests now verify MTM schema/path preservation and terminal liquidation reconciliation.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 622 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| application/package version consistency | PASSED: app and package are 1.26.6 |
| static Alembic head check | PASSED: one head, `0014_ui_exposure_ledger` |
| release integrity / manifest | PASSED: 222 files checked, 222 manifest entries |
| clean ZIP test and re-extraction | PASSED: one root directory; `unzip -t` clean; re-extracted manifest verified; forbidden-artifact scan clean |

## Environment-dependent checks

| Check | Result |
|---|---|
| `python manage.py doctor` | FAILED as expected for sandbox: `.env` absent, default secrets unresolved, `psql`/`pg_dump`/`pg_restore` absent, PostgreSQL unreachable |
| `python manage.py test --require-integration` | FAILED before test execution: neither `POSTGRES_ADMIN_URL` nor `TEST_DATABASE_URL` is configured |

## Warnings

62 warnings are Joblib/NumPy and pandas timedelta deprecations. The new regression tests add no warning category; one additional occurrence comes from extending an existing timedelta assertion.

## Release boundary

- Database migration: none.
- Public HTTP API: unchanged.
- `.env` variables: unchanged.
- Model feature/label/runtime artifact schemas: unchanged.
- Trading/risk/model-quality thresholds: unchanged.
- Advisory-only/read-only Bybit boundary: unchanged.
- Experiment period-return schema: `observed-opportunity-covered-hourly-capital-return-path-v2` → `observed-opportunity-covered-hourly-mark-to-market-capital-return-path-v3`.
- Active artifacts remain runnable. Existing experiment families with successful v2 trials require rerun before normal activation.
