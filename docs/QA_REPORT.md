# QA Report — 1.22.0

Date: 2026-07-05
Scope: point-in-time funding-interval history in research settlement replay, market-context features and artifact validation.

## Environment

- Input release: `1.21.0`.
- Input ZIP: `cost_aware_momentum-main.zip`.
- Input ZIP SHA-256: `64c82a5cb35ff75934f13a58f63ede67ef61c295f34ae3fb8fed8e5fe83eb3ce`.
- Checks executed in isolated environment `/mnt/data/cam_1210_venv`; no production database was used.
- Python: `3.13.5`; project requirement remains Python `>=3.12`.

The global host environment was unsuitable because it lacked project packages (`ruff`, `psycopg`) and contained an unrelated `moviepy`/`pillow` dependency conflict. All authoritative baseline and post-change results below come from the isolated project environment.

## Baseline before changes

| Check | Result |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `582 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

The four skipped tests require a separately configured PostgreSQL integration database.

## Confirmed defect and red evidence

`app/ml/lifecycle.py::load_training_market_data` read all instrument-spec rows but reduced them to one latest interval per symbol. `HistoricalFundingTimeline` and `build_market_context_frame` therefore applied that latest value to every historical timestamp.

The new regression module was run against untouched 1.21.0 before production changes:

```text
3 failed
TypeError: HistoricalFundingTimeline.__init__() got an unexpected keyword argument 'interval_history'
TypeError: build_market_context_frame() got an unexpected keyword argument 'funding_interval_history'
```

The tests encode independent expected behavior: a complete 8-hour to 4-hour settlement transition must remain complete, a missing settlement under the new 4-hour regime must still fail closed, and funding age must equal 0.5 in both a four-hours-old/8-hour regime and a two-hours-old/4-hour regime.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests migrations manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `586 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

Focused module: `4 passed`.

## Doctor and integration status

- `python manage.py doctor`: NOT APPLICABLE to the isolated external environment. It exited with `Виртуальная среда не найдена. Сначала выполните: python manage.py setup` because the release tree intentionally has no project-local `.venv`; equivalent dependency, syntax, static-analysis, unit and Alembic-head checks were executed with `/mnt/data/cam_1210_venv`.
- `python manage.py test --require-integration`: NOT RUN because no isolated `TEST_DATABASE_URL` was supplied. It was not pointed at a user or production database.
- PostgreSQL query/migration smoke: NOT RUN. No migration was added; head remains `0014_ui_exposure_ledger`.
- Live Bybit/API and browser flows: NOT RUN; this work package changes offline research/training semantics and uses existing read-only data.

## Residual warnings

The 61 warnings are existing NumPy/joblib/pandas deprecations. The focused new tests introduce no new warning class.

## Release verification

- Clean staged tree: `230` files including `SHA256SUMS`; checksum manifest covers and verifies `229/229` other files.
- Staged tree passed dependency check, compileall, Ruff, full pytest (`586 passed, 4 skipped`), frontend syntax and Alembic head `0014_ui_exposure_ledger`.
- Forbidden cache, credential, build, model-artifact and database-dump paths were absent before packaging.
- Advisory-only Bybit mutation scan, suspicious-secret scan and trailing-whitespace scan: PASSED.
- Final archive contains one root directory `cost_aware_momentum-1.22.0`, passes `unzip -t`, and a fresh extraction repeats checksum, compileall, Ruff, pytest, frontend and Alembic-head checks.
- Final ZIP SHA-256 is recorded in the delivery response and is not embedded recursively inside the archive.
- No profitability or recommendation-frequency claim is made.
