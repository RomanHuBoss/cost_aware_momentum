# QA Report

Release: **1.26.7**

Date: **2026-07-06**
Scope: **cost-stress experiment promotion gate**

## Environment

- Python: 3.13.5 in isolated virtual environment `/mnt/data/cam_venv`.
- Project requirement: Python >=3.12.
- Node syntax check available.
- Separate PostgreSQL integration database: not configured.
- Host/global Python was unsuitable: `ruff`/`psycopg` were absent and global `pip check` had an unrelated MoviePy/Pillow conflict.

## Baseline before changes

| Check | Result |
|---|---|
| input ZIP SHA-256 | `1ef3ca05de319366abc9db5fc207b59d8814f54d1728016ab6f4b7fd9a9ed3ab` |
| source version | 1.26.6 |
| source inventory | 223 files; 73 app, 83 tests, 9 docs; 14 migrations; head `0014_ui_exposure_ledger` |
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED in isolated venv |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 622 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |

## Confirmed gap and red evidence

`policy_backtest` computed ×1.5/×2 terminal stress totals, but successful experiment events persisted only nominal period returns. `analyze_experiment_family` therefore selected and approved configurations without any cost-stress path or sign check. This contradicted the specification's mandatory commission/slippage stress analysis and allowed normal promotion despite a negative stressed capital result.

Red command:

```text
python -m pytest -q \
  tests/unit/test_experiment_observed_period_path_2026_07_05.py::test_experiment_evidence_carries_aligned_cost_stress_paths \
  tests/unit/test_experiment_observed_period_path_2026_07_05.py::test_success_event_without_cost_stress_evidence_is_rejected
```

Before implementation: **2 failed** (`KeyError: cost_stress`; missing evidence was accepted).
After implementation: **2 passed**.

## Added/extended regression coverage

- ×1.5/×2 paths align exactly with nominal timestamps and independently reconcile to terminal compounded returns.
- Known fee/slippage example verifies stressed entry and terminal arithmetic.
- Missing/legacy stress evidence fails closed.
- Negative selected ×2 path returns `REJECTED_COST_STRESS`.
- READY report without stress evidence is rejected.
- Legacy persisted promotion gate v2 cannot authorize activation.
- Existing atomic promotion, policy binding and dependence tests now carry valid stress evidence.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 627 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| application/package version consistency | PASSED: 1.26.7 |
| Alembic heads | PASSED: one head, `0014_ui_exposure_ledger` |
| release manifest | PASSED: 224 files verified by `sha256sum -c SHA256SUMS` |
| clean ZIP/re-extraction | PASSED: one root directory, `unzip -t` clean, re-extracted manifest and forbidden-artifact scan clean |

## Environment-dependent checks

| Check | Result |
|---|---|
| `python manage.py doctor` | FAILED: `.env` absent, default secrets unresolved, `psql`/`pg_dump`/`pg_restore` absent, PostgreSQL unreachable |
| `python manage.py test --require-integration` | NOT RUN: neither `POSTGRES_ADMIN_URL` nor `TEST_DATABASE_URL` is configured |

## Warnings

62 warnings are existing Joblib/NumPy and pandas timedelta deprecations. No new warning category was introduced.

## Release boundary

- Database migration: none.
- Public HTTP API: unchanged.
- `.env` variables: unchanged.
- Model feature/label/runtime artifact schemas: unchanged.
- Recommendation/risk/quality thresholds: unchanged.
- New governance invariant: selected trial terminal capital return must be non-negative at both ×1.5 and ×2 costs.
- Experiment report schema: v3 → v4. Promotion gate schema: v2 → v3.
- Active artifacts remain runnable. Existing successful experiment evidence without cost-stress v1 must be rerun before normal promotion.
