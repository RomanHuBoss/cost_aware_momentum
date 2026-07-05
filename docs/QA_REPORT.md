# QA Report

Release: **1.26.2**

Date: **2026-07-05**
Scope: **deferred governed promotion of registered model candidates**

## Environment

- Python: 3.13.5 in isolated virtual environment `/mnt/data/cam_venv`.
- Project requirement: Python >=3.12.
- Node syntax check available.
- Separate PostgreSQL integration database: not configured in this execution environment.

## Baseline before changes

| Check | Result |
|---|---|
| `python -m pip check` | PASSED in isolated venv |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 606 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| static Alembic head check | PASSED: `0014_ui_exposure_ledger` |
| package/application version consistency | PASSED: `1.26.2` |
| `python -B -m scripts.release_integrity` | PASSED: 211 eligible files / 211 manifest entries before packaging |

The host/global Python environment was not used as the project baseline: it had unrelated `moviepy`/`pillow` dependency conflicts, lacked `ruff` and `psycopg`, and pytest collection failed. A clean editable install with the project's `dev` extra was therefore used for comparable pre/post results.

## Red → green evidence

Initial command:

```text
python -m pytest -q tests/unit/test_deferred_model_promotion.py
```

Before implementation: **2 failed** because `BackgroundTrainer` had neither `_pending_auto_activation_candidate` nor `reconcile_pending_activation`.

After implementation: **3 passed**. The third test explicitly verifies that non-READY experiment evidence cannot activate a candidate.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 609 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | FAILED (environment): no `.env`, default secrets, PostgreSQL client tools absent, local PostgreSQL unavailable |
| `python manage.py test --require-integration` | NOT RUN: neither `TEST_DATABASE_URL` nor `POSTGRES_ADMIN_URL` was configured |

## Warnings

61 warnings are pre-existing dependency/NumPy deprecations; this patch did not add a new warning category.

## Release boundary

- Database migration: none.
- Artifact schema: unchanged.
- Public HTTP API: unchanged.
- Advisory-only/read-only exchange boundary: unchanged.
- No `.env`, credentials, model artifacts, caches or database dumps are intended for the release ZIP.
