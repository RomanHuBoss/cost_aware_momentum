# QA Report

Release: **1.28.1**

Date: **2026-07-06**  
Scope: **critical drift evidence precedence**

## Environment

- Python: 3.13.5 in isolated virtual environment `/mnt/data/cam_iter2/venv`.
- Project requirement: Python >=3.12.
- Node syntax check available.
- Separate PostgreSQL integration database: not configured.
- Input archive SHA-256: `f85389e3753cbd4bb24034cfbcae7479e260300066dbf58545338a3eb0eb2b3d`.

## Baseline before changes

| Check | Result |
|---|---|
| source version | 1.28.0 |
| source inventory | 231 files; 93 production Python, 85 test Python, 12 docs; 14 migration revisions; head `0014_ui_exposure_ledger` |
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 641 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |

## Confirmed defect and red evidence

`app/ml/drift.py` assigned `BLOCKED` a higher status rank than `CRITICAL`, and `app/services/drift_monitor.py` directly overwrote an evaluated report with `BLOCKED` when failed jobs, invalid coverage or incomplete mature outcomes were present.

Reproduced counterexample:

- feature PSI: `11.512865346214785`;
- alert: `feature_distribution_drift`;
- inference coverage: 60% against required 80%;
- baseline overall status: `BLOCKED`;
- publication consequence: no critical quarantine latch.

Original red command:

```text
python -m pytest -q tests/unit/test_critical_drift_evidence_precedence_2026_07_06.py
```

Result before implementation:

```text
2 failed, 1 passed
expected CRITICAL, actual BLOCKED
```

## Added/extended regression coverage

- Critical feature PSI dominates incomplete inference coverage while both evidence types remain disclosed.
- Incomplete mature outcomes cannot suppress independent critical feature drift.
- Incomplete outcomes without independent critical evidence remain `BLOCKED` and non-quarantining.
- Existing low-coverage/missingness and delayed-label tests now assert the stronger fail-closed status semantics.
- Existing persisted critical quarantine, worker ordering and plan/signal interlock tests remain green.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 644 passed, 4 skipped, 62 warnings |
| targeted drift/interlock suite | PASSED: 20 passed |
| `node --check web/js/app.js` | PASSED |
| application/package version consistency | PASSED: 1.28.1 |
| Alembic heads | PASSED: one head, `0014_ui_exposure_ledger` |
| release integrity | PASSED: 233 eligible files checked against 233 manifest entries |
| final ZIP test/re-extraction | PASSED: one root directory, compressed data clean, re-extracted manifest verified |
| final release inventory | PASSED: 234 files including `SHA256SUMS`; 93 production Python, 86 test Python, 13 documentation files |

## Environment-dependent checks

| Check | Result |
|---|---|
| `python manage.py doctor` | FAILED preflight: project-local managed virtualenv is absent; `.env`/PostgreSQL checks were not reached |
| `python manage.py test --require-integration` | FAILED preflight for the same managed-virtualenv requirement; PostgreSQL integration tests were not executed |

## Warnings

62 warnings are existing Joblib/NumPy and pandas timedelta deprecations. No new warning category was introduced.

## Release boundary

- Database migration: none.
- Public HTTP request/response schema: unchanged.
- `.env` variables/defaults: unchanged.
- Model feature/label/runtime artifact schemas: unchanged.
- Drift reference schema: unchanged at v2.
- Drift report schema: v2 → v3 with separated critical/blocking/warning evidence.
- Signal direction, execution-plan sizing, TP/SL and actionability thresholds: unchanged.
- Existing persisted v2 critical reports remain effective in the status/model-version based guard.
