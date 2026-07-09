# QA report — 1.52.20

Date: 2026-07-09  
Scope: `locked-orderbook-validation`

## Baseline before code changes

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 10.04s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Red evidence

The new regression was added before changing `app/risk/liquidity.py`.

Command:

```bash
python -m pytest -q tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book
```

Result on unpatched 1.52.19 code:

```text
F                                                                        [100%]
FAILED tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book - Failed: DID NOT RAISE <class 'ValueError'>
1 failed in 0.89s
```

This proved that a locked top-of-book with `best_ask == best_bid` passed normalization and could become orderbook execution evidence.

## Green evidence

New regression plus existing crossed-book contract:

```bash
python -m pytest -q \
  tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book \
  tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_uses_matching_engine_time_and_rejects_crossed_book
```

Result after patch:

```text
..                                                                       [100%]
2 passed in 0.79s
```

Related orderbook/liquidity subset:

```bash
python -m pytest -q tests/unit/test_orderbook_execution_quality_2026_07_05.py tests/unit/test_orderbook_vwap_sizing_integrity_2026_07_08.py
```

Result after patch:

```text
...................                                                      [100%]
19 passed in 2.64s
```

Post targeted counts: passed 21 / failed 0 / skipped 0 / xfailed 0 / errors 0 across the two post-fix targeted commands.

## Post-check after patch

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | FAILED | same sandbox dependency conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| new locked-orderbook regression | PASSED | `1 passed in 0.78s` |
| orderbook related subset | PASSED | `19 passed in 2.64s` |
| `python -m pytest -q` | FAILED | `62 errors in 6.99s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |

Full pytest counts after patch: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection, because this sandbox lacks `psycopg`.

## Not verified here

- PostgreSQL integration tests.
- `manage.py doctor` against a real local PostgreSQL configuration.
- `python -m ruff check .`, because ruff is not installed in the sandbox.
- `python -m pip check` clean status, because the global sandbox has an unrelated `moviepy`/`pillow` conflict.
