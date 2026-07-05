# QA Report — 1.10.0

Date: 2026-07-05
Scope: execution-entry alignment for training labels, artifacts, promotion gate and research backtest.

## Environment

- Python: 3.13.5
- Project requirement: Python >=3.12
- Input release: 1.9.7
- Output release: 1.10.0
- Alembic revisions: 9; expected head `0009_candle_receipt_availability`

## Baseline before code changes

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Host-level unrelated conflict: `moviepy 2.2.1` requires `pillow<12`, host has `pillow 12.2.0`. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 461 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python manage.py doctor` | NOT RUN | Baseline project virtual environment/runtime configuration was not provisioned. |
| `python manage.py test --require-integration` | NOT RUN | No isolated `TEST_DATABASE_URL` or `POSTGRES_ADMIN_URL`; production database was not used. |

Before the reproducible baseline, project dev dependencies were installed editable because the host initially lacked `psycopg` and `ruff`; the first raw pytest attempt therefore had collection errors and was not treated as code baseline.

## Red → green

New test command before implementation:

```text
python -m pytest -q tests/unit/test_execution_aware_training_entry_2026_07_05.py
```

Red result: 2 failed. Both failed with `TypeError: make_barrier_dataset() got an unexpected keyword argument 'entry_spread_bps'`.

Green result after implementation: the file now contains 3 passing tests, covering direction-specific entry, invalid spread, and invalid configuration.

## Post-change checks

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Same external host `moviepy`/`pillow` conflict; project dependency graph was not the cause. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 468 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m pytest -q -rs tests/integration_postgres` | SKIPPED | 4 skipped because `TEST_DATABASE_URL` is not configured. |
| `python manage.py doctor` | FAILED (environment) | `.venv` absent; command instructs to run `python manage.py setup`. |
| `python manage.py test --require-integration` | NOT RUN | No isolated PostgreSQL test database configured. |

## Interpretation

Static/unit verification is green. PostgreSQL migration/integration behavior and configured local runtime smoke were not verified in this environment. No database schema changed in this release.

## Release archive verification

- Clean staged tree: 169 eligible files; no forbidden cache, credential, model artifact or dump files.
- `scripts/release_integrity.py --write` and subsequent verification: PASSED, 169/169 manifest entries.
- `unzip -t`: PASSED.
- Re-extracted archive full suite: 468 passed, 4 skipped; compileall, Ruff and Node syntax checks PASSED.
