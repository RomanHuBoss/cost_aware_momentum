# QA Report

Release: **1.28.2**

Date: **2026-07-06**  
Scope: **point-in-time training universe integrity**

## Environment

- Python: 3.13.5 in isolated project virtual environment `/mnt/data/cam_work/cost_aware_momentum-main/.venv`.
- Project requirement: Python >=3.12.
- Node syntax check available.
- Separate PostgreSQL integration database: not configured.
- Input archive SHA-256: `8552ca31c0879d8556754f92f34b58506e1ae2865e0cb96424124e79e7919ec4`.
- Input documentation limitation: files named in the generic iteration prompt (`docs/ARCHITECTURE.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`) were absent from the supplied archive; code and available repository evidence were used instead.

## Baseline before changes

| Check | Result |
|---|---|
| source version | 1.28.1 |
| source inventory | 234 files; 93 `app/scripts` Python + `manage.py`; 86 test Python; 12 `docs/*.md` + README; 14 migration revisions; head `0014_ui_exposure_ledger` |
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED in isolated venv: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 644 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |

The host/global Python environment was not used as release evidence because project dependencies were initially absent and an unrelated global Pillow/MoviePy conflict existed. The isolated project venv passed `pip check`.

## Confirmed defect and red evidence

`app/ml/lifecycle.py::_select_training_symbols` selected the current top-turnover symbols from the newest `TickerSnapshot`, then applied that list to the historical lookback. This used selection information later than the label cutoff and could prefer a newly active high-turnover symbol without enough historical rows.

A second time-of-check/time-of-use inconsistency existed in `app/workers/trainer.py`: `due_reason()` persisted a profile for one symbol set, but `run_training_once()` resolved the dynamic ranking again before loading data. The candidate could therefore be fit on a different cohort than the trigger profile.

Original red command:

```text
python -m pytest -q tests/unit/test_training_universe_integrity_2026_07_06.py
```

Result before implementation:

```text
1 failed
actual: ['HOT_NEW_USDT']
expected: ['BTCUSDT', 'ETHUSDT']
```

## Added regression coverage

- Dynamic capped selection does not query `ticker_snapshots`.
- Selection query is bounded by lookback and label cutoff.
- Minimum eligible rows and reach-to-cutoff requirements are present.
- Deterministic mature-history cohort replaces the artificial latest-turnover symbol.
- Existing lifecycle, activation, recovery and data-profile tests remain green.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 645 passed, 4 skipped, 62 warnings |
| targeted training-universe regression | PASSED: 1 passed |
| related trainer/lifecycle suite | PASSED: 24 passed |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0014_ui_exposure_ledger` |
| application/package version consistency | PASSED: 1.28.2 |
| release integrity | PASSED: 236 eligible files checked against 236 manifest entries |
| final ZIP test/re-extraction | PASSED: one root directory; `unzip -t` clean; re-extracted manifest verified |
| final release inventory | PASSED: 237 files including `SHA256SUMS`; 94 production Python including `manage.py`; 87 test Python; 13 `docs/*.md` |

## Environment-dependent checks

| Check | Result |
|---|---|
| `python manage.py doctor` | FAILED environment preflight: `.env` absent; default secrets; `psql`/`pg_dump`/`pg_restore` absent; PostgreSQL connection refused |
| `python manage.py test --require-integration` | NOT RUN: `POSTGRES_ADMIN_URL` or `TEST_DATABASE_URL` is required |

## Warnings

62 warnings are existing Joblib/NumPy and pandas timedelta deprecations. No new warning category was introduced.

## Release boundary

- Database migration: none.
- Public HTTP request/response schema: unchanged.
- `.env` variables/defaults: unchanged.
- Model feature/label/runtime artifact schemas: unchanged.
- Risk, cost, direction, TP/SL, actionability and activation thresholds: unchanged.
- Dynamic training-universe selection semantics changed from latest-turnover ranking to label-eligible historical coverage ranking.
- Existing active artifacts remain runnable; retraining is recommended for new governed evidence under the corrected cohort contract.
