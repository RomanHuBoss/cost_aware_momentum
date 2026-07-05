# QA Report

Release: **1.26.3**

Date: **2026-07-05**
Scope: **exact experiment-to-deployment policy binding for model promotion**

## Environment

- Python: 3.13.5 in isolated virtual environment `/mnt/data/cam_iter2_venv`.
- Project requirement: Python >=3.12.
- Node syntax check available.
- Separate PostgreSQL integration database: not configured.
- Host/global Python was not used for comparable baseline/post results: it lacked project packages/ruff and had an unrelated Pillow/MoviePy dependency conflict.

## Baseline before changes

| Check | Result |
|---|---|
| `python -m pip check` | PASSED in isolated venv |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 609 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| package/application version | PASSED: 1.26.2 |

## Confirmed defect and red evidence

`evaluate_experiment_promotion_gate` verified selected experiment evidence only against model version, artifact SHA-256 and horizon. Deployment-relevant configuration was ignored. A trial could therefore be selected under different fees, slippage, stop-gap reserve or EV/RR thresholds from the policy used after activation.

Red command:

```text
python -m pytest -q tests/unit/test_experiment_policy_binding_2026_07_05.py
```

Before implementation: **2 failed** with `TypeError: evaluate_experiment_promotion_gate() got an unexpected keyword argument 'expected_policy_binding'`.

After implementation: **4 passed**. The suite covers policy mismatch rejection, exact match acceptance, invalidation after deployment settings change and rejection of legacy gates without binding.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 613 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| application/package version consistency | PASSED: 1.26.3 |
| static Alembic head check | PASSED: one head, `0014_ui_exposure_ledger` |
| `python -B -m scripts.release_integrity --write` | PASSED: 214 eligible files / 214 manifest entries |
| targeted activation/lifecycle suite | PASSED: 21 tests before final added assertions; full suite covers final state |

## Environment-dependent checks

| Check | Result |
|---|---|
| `python manage.py doctor` | FAILED due environment: `.env` absent, default secrets, `psql`/`pg_dump`/`pg_restore` absent and PostgreSQL unavailable on localhost |
| `python manage.py test --require-integration` | NOT RUN as integration evidence: command stopped because neither `TEST_DATABASE_URL` nor `POSTGRES_ADMIN_URL` was configured |

The commands were run through a temporary project-local `.venv` symlink to the isolated environment and the symlink was removed immediately afterward.

## Warnings

61 warnings are pre-existing Joblib/NumPy and pandas timedelta deprecations. This patch did not add a warning category.

## Release boundary

- Database migration: none.
- Public HTTP API: unchanged.
- `.env` variables: unchanged.
- Advisory-only/read-only Bybit boundary: unchanged.
- Runtime artifact schema remains readable; new candidates persist an additional policy-binding metric.
- Promotion gate schema changed from v1 to v2.
- Already active artifacts remain runnable. Pre-1.26.3 inactive candidates require retraining for normal promotion because they lack immutable policy binding.
