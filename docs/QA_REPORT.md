# QA Report

Release: **1.50.0**

Date: **2026-07-07**

Scope: **all-opportunity production drift telemetry**

## Input and baseline

- Input archive SHA-256: `acc2869c3265fc3ca4db7b3a94dd9b3555197dee8d6167e1bb2717df9d16fd8e`.
- Input version: `1.49.1`; Alembic head: `0017_model_artifact_blobs`.
- Python: `3.13.5` in an isolated virtual environment.
- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: PASSED — `829 passed, 8 skipped, 62 warnings`.
- `node --check web/js/app.js`: PASSED.
- `python manage.py doctor`: NOT RUN to completion; the command requires a project-local environment created by `manage.py setup`, while QA used an external isolated venv.
- `python manage.py test --require-integration`: NOT RUN; no isolated PostgreSQL `TEST_DATABASE_URL` was available. No production database was used.

The first attempt in the global environment was not accepted as baseline because project dependencies (`psycopg`, `ruff`) were absent and an unrelated global `moviepy/Pillow` conflict existed.

## Confirmed defect/gap

`app/services/drift_monitor.py` derived feature/probability PSI from `MarketSignal.feature_snapshot`. `MarketSignal` exists only after downstream policy filters. The resulting production sample was selected on spread/funding/EV/RR/publication and could omit nearly all model-evaluable no-trade opportunities.

Severity: **high** (model-safety evidence can be incomplete and policy-conditioned; it does not itself prove the source of realized losses).

## Red → green

- Red command: `python -m pytest -q tests/unit/test_all_opportunity_drift_telemetry_2026_07_07.py` against untouched 1.49.1.
- Red result: collection error, `ImportError: cannot import name 'ModelInferenceObservation'`.
- Green targeted result: 5 tests passed across the new telemetry and migration-contract suites; the complete focused drift set passed after fixture alignment.
- Full post-change result: `832 passed, 8 skipped, 62 warnings`.

## Post-change checks

- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: PASSED — `832 passed, 8 skipped, 62 warnings`.
- `node --check web/js/app.js`: PASSED.
- Alembic graph: one head, `0018_inference_observations`; every revision ID fits the standard 32-character version column.
- Alembic PostgreSQL offline SQL generation from base to head: PASSED — 1,448 lines.
- PostgreSQL live migration/integration: NOT RUN; an isolated server was unavailable.

## Release conclusion

Static/unit evidence is green. The release remains advisory-only and PostgreSQL-only. No profitability claim is made. Operator acceptance still requires migration on an isolated/staging PostgreSQL database and prospective drift warm-up/forward observation.
