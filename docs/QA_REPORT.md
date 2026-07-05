# QA Report — 1.11.0

Date: 2026-07-05

Scope: purged expanding walk-forward validation inside development period, with separate final holdout.

## Environment

- Python: 3.13.5
- Project requirement: Python >=3.12
- Input release: 1.10.0
- Output release: 1.11.0
- Input ZIP SHA-256: `8a30282ebd65c7876052eef01e72f1f00a00487c244bcd36f0d6156aa4ef4597`
- Alembic revisions: 9; expected head `0009_candle_receipt_availability`

## Baseline before code changes

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Host-level unrelated conflict: `moviepy 2.2.1` requires `pillow<12`, host has `pillow 12.2.0`. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 468 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python manage.py doctor` | FAILED (environment) | Project `.venv` was not provisioned; command requested `python manage.py setup`. |
| `python manage.py test --require-integration` | NOT RUN | No isolated `TEST_DATABASE_URL` or `POSTGRES_ADMIN_URL`; production database was not used. |

## Red → green

Initial acceptance command before implementation:

```text
python -m pytest -q tests/unit/test_walk_forward_validation_2026_07_05.py
```

Red result: collection failed with `ImportError: cannot import name 'expanding_walk_forward_splits' from 'app.ml.training'`.

Green result: 4 tests passed in the new module. Additional gate/runtime regressions bring the full-suite increase to eight tests.

## Post-change checks

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Same external host `moviepy`/`pillow` conflict; project dependencies were not changed. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 476 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m pytest -q -rs tests/integration_postgres` | SKIPPED | 4 skipped because `TEST_DATABASE_URL` is not configured. |
| `python manage.py doctor` | FAILED (environment) | `.venv` absent; no configured local runtime smoke was claimed. |
| `python manage.py test --require-integration` | NOT RUN | No isolated PostgreSQL test database configured. |

## Release archive verification

- Clean staged tree: 172 eligible files; no forbidden caches, credentials, model artifacts or dumps.
- `scripts/release_integrity.py --write` and verification: PASSED, 172/172 entries.
- `unzip -t`: PASSED.
- Fresh re-extraction: release integrity, Ruff, compileall and Node syntax PASSED; full suite 476 passed, 4 skipped.

## Interpretation

Static and unit verification is green. PostgreSQL integration/migration execution and configured local runtime smoke were not verified in this environment. No database schema, API contract or `.env` setting changed. Technical correctness does not establish a profitable trading edge.
