# QA Report — 1.13.0

Date: 2026-07-05

Scope: progressive hourly mark-price history, realized-only intrahorizon mark-to-market and conservative isolated-margin liquidation evidence, with explicit protection against future-mark look-ahead.

## Environment

- Python: 3.13.5
- Project requirement: Python >=3.12
- Input release: 1.12.0
- Output release: 1.13.0
- Input ZIP SHA-256: `292ecb76a87438dfe08700a28d7b822c897631357b9d1562d9551b88c0195a6e`
- Input release integrity: PASSED, 176/176 manifest entries
- Alembic revisions: 9; expected head `0009_candle_receipt_availability`

## Baseline before code changes

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Host-level unrelated conflict: `moviepy 2.2.1` requires `pillow<12`, host has `pillow 12.2.0`. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 484 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python manage.py doctor` | FAILED (environment) | Project `.venv` was not provisioned; command requested `python manage.py setup`. |
| `python manage.py test --require-integration` | NOT RUN | No isolated `TEST_DATABASE_URL`; production database was not used. |

## Red → green

Acceptance command against untouched 1.12.0 source after copying the new regression module into its test tree:

```text
python -m pytest -q tests/unit/test_intrahorizon_liquidation_mtm_red_2026_07_05.py
```

Red result: collection failed with `ModuleNotFoundError: No module named 'app.ml.mtm'` (exit 2).

Green command on 1.13.0:

```text
python -m pytest -q tests/unit/test_intrahorizon_liquidation_mtm_2026_07_05.py
```

Green result: 9 passed.

The tests independently cover LONG/SHORT directional MTM, liquidation before a later last-price exit, exit-at-open ordering, adverse funding timing, invalid/misaligned paths, exact mark-timeline attachment, missing-bar fail-closed behavior, future-mark look-ahead isolation and explicit mark-price backfill typing.

## Post-change checks

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Same external host `moviepy`/`pillow` conflict; project dependencies were not changed. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 493 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| Targeted new module | PASSED | 9 passed. |
| `python -m pytest -q -rs tests/integration_postgres` | SKIPPED | 4 skipped because `TEST_DATABASE_URL` is not configured. |
| `python manage.py doctor` | FAILED (environment) | `.venv` absent; no configured local runtime smoke was claimed. |
| `python manage.py test --require-integration` | NOT RUN | Command stops at missing project `.venv`; no isolated PostgreSQL test database was available. |
| Order-mutation source scan | PASSED | No create/amend/cancel order endpoint or client method found. |

## Interpretation

Static and unit verification is green. The new logic is intentionally a conservative hourly isolated-margin research proxy. It does not claim exact historical Bybit liquidation: point-in-time maintenance-margin/risk tiers, liquidation fee, sub-hour event ordering, cross/portfolio margin, ADL, insurance-fund and exchange fill mechanics remain outside this release.

PostgreSQL integration, a real multi-page Bybit mark-price backfill, full-dataset retraining and paper/shadow forward evidence were not executed in this environment. No database migration, public API or new `.env` contract was introduced. `DEFAULT_LEVERAGE` is now part of the immutable research artifact assumptions. Technical correctness does not establish a profitable trading edge.

## Release archive verification

- Clean staged tree: 180 eligible files; no forbidden caches, credentials, model artifacts or dumps.
- `scripts/release_integrity.py --write` and verification: PASSED, 180/180 entries.
- `unzip -t`: PASSED.
- Fresh re-extraction integrity: PASSED, 180/180 entries.
- Fresh re-extraction compileall, Ruff and Node syntax: PASSED.
- Fresh re-extraction full suite: 493 passed, 4 skipped.
