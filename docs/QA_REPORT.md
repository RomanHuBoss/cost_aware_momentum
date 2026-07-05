# QA Report — 1.17.0

Date: 2026-07-05

Scope: immutable final-holdout drift reference, active-version production monitoring, fixed-bin feature/probability PSI, coverage/missingness, selected-direction calibration drift, actionability-density drift and operational heartbeat/report integration.

## Environment

- Python: 3.13.5
- Project requirement: Python >=3.12
- Isolated validation environment: `/mnt/data/cam_venv_115`
- Input release: 1.16.0
- Output release: 1.17.0
- Input ZIP SHA-256: `9bfd32ad4907b37790111b583e7f91e6f0faf603da8634160d23754820ef143e`
- Input Alembic head: `0011_selection_experiment`
- Output Alembic head: `0011_selection_experiment`
- Baseline tree: 78 app/script Python files, 66 test Python files, 16 documentation files, 11 migration Python files
- Post-change source tree: 81 app/script Python files, 68 test Python files, 16 documentation files, 11 migration Python files

No production PostgreSQL database was contacted.

## Baseline before code changes

| Check | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5. |
| `python -m pip check` | PASSED | No broken requirements in the isolated environment. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 531 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m alembic heads` | PASSED | Single head `0011_selection_experiment`. |

## Red → green

The new regression module was copied into an untouched 1.16.0 tree and executed:

```text
python -m pytest -q tests/unit/test_production_drift_monitoring_2026_07_05.py
```

Red result during collection:

```text
ModuleNotFoundError: No module named 'app.ml.drift'
```

Green result after implementation:

```text
8 passed
```

One additional runtime regression verifies that an all-direction calibration reference cannot be loaded as the selected-direction production contract. Existing policy tests also verify selected-cohort calibration evidence. Total suite growth: 9 passing tests.

## Post-change checks

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 540 passed, 4 skipped, 61 pre-existing dependency/test deprecation warnings. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m alembic heads` | PASSED | Single head `0011_selection_experiment`. |
| `python -m pytest -q -rs tests/integration_postgres` | SKIPPED | 4 skipped because `TEST_DATABASE_URL` is not configured. |
| `python manage.py doctor` | FAILED (environment) | Project-local `.venv` is absent; validation used the separate isolated environment. |
| `python manage.py test --require-integration` | NOT RUN | No isolated PostgreSQL test database was configured. |

## Drift-contract checks

- Reference features are taken only from `split.x_test` and omit scenario direction.
- Probability references include both LONG and SHORT vectors, matching production directional snapshots.
- Calibration reference uses one policy-selected direction per symbol/timestamp, matching resolved production signal outcomes.
- Histogram boundaries are fixed in the artifact; production observations do not redefine bins.
- Missing, non-finite and insufficient observations do not produce a false healthy state.
- Coverage is based on successful hourly inference scope/completion evidence.
- Failed hourly inference jobs and invalid coverage accounting explicitly block the report.
- Signals and outcomes are filtered to the active model version.
- Calibration waits for resolved `SignalOutcome` evidence.
- Critical or blocked drift degrades worker heartbeat.
- `automatic_model_action` is always `none`; no activation, deactivation, rollback or gate weakening is performed.
- Runtime and quality gate require exact drift-reference and selected calibration-cohort schemas.

## Release archive verification

This section is finalized after staging and fresh extraction.

| Check | Status | Result |
|---|---|---|
| Clean staged release tree | PASSED | One root directory; no caches, credentials, dumps or model artifacts. |
| SHA256 manifest | PASSED | 204 eligible files and 204 manifest entries. |
| `unzip -t` | PASSED | No archive errors. |
| Manifest after fresh extraction | PASSED | 204/204 files. |
| Full suite after fresh extraction | PASSED | 540 passed, 4 skipped, 61 warnings. |
| Frontend syntax after extraction | PASSED | `node --check web/js/app.js`. |
| Alembic head after extraction | PASSED | Single head `0011_selection_experiment`. |

## Interpretation

The release adds operational evidence for distribution, calibration, coverage and actionability changes after activation. It does not prove causality or profitability, implement multivariate drift detection, compensate statistically for delayed labels, optimize control limits, or perform automatic model rollback.
