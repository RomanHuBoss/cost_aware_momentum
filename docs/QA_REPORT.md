# QA Report — 1.12.0

Date: 2026-07-05

Scope: progressive historical funding backfill and settlement-timestamp replay for research realized costs, with explicit protection against future-funding look-ahead.

## Environment

- Python: 3.13.5
- Project requirement: Python >=3.12
- Input release: 1.11.0
- Output release: 1.12.0
- Input ZIP SHA-256: `baa8f91d086ed91358ae67a4c6f9a0f646963ad6f006bcae7e26e3dcb45442bd`
- Alembic revisions: 9; expected head `0009_candle_receipt_availability`

## Baseline before code changes

The first host invocation lacked `ruff` and the PostgreSQL driver. After installing the project-declared tooling in the review environment, the reproducible code baseline was:

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Host-level unrelated conflict: `moviepy 2.2.1` requires `pillow<12`, host has `pillow 12.2.0`. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 476 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python manage.py doctor` | FAILED (environment) | Project `.venv` was not provisioned; command requested `python manage.py setup`. |
| `python manage.py test --require-integration` | NOT RUN | No isolated `TEST_DATABASE_URL`; production database was not used. |

## Red → green

Acceptance command against the untouched 1.11.0 source:

```text
python -m pytest -q tests/unit/test_historical_funding_replay_2026_07_05.py
```

Red result: collection failed with `ModuleNotFoundError: No module named 'app.ml.funding'`.

Green result: the funding-specific module contains 7 passing tests. One additional quality-gate regression verifies that future actual settlement rates cannot be declared as ex-ante policy input.

## Post-change checks

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Same external host `moviepy`/`pillow` conflict; project dependencies were not changed. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 484 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m pytest -q -rs tests/integration_postgres` | SKIPPED | 4 skipped because `TEST_DATABASE_URL` is not configured. |
| `python manage.py doctor` | FAILED (environment) | `.venv` absent; no configured local runtime smoke was claimed. |
| `python manage.py test --require-integration` | NOT RUN | Command stops at missing project `.venv`; no isolated PostgreSQL test database was available. |

## Interpretation

Static and unit verification is green. PostgreSQL integration, a real multi-page Bybit funding backfill, full-dataset retraining and paper/shadow forward evidence were not executed in this environment. No database migration, public API or `.env` contract changed. Technical correctness does not establish a profitable trading edge.

## Release archive verification

- Clean staged tree: 176 eligible files; no forbidden caches, credentials, model artifacts or dumps.
- `scripts/release_integrity.py --write` and verification: PASSED, 176/176 entries.
- Archive and fresh re-extraction checks are recorded in the iteration report supplied with the release.
