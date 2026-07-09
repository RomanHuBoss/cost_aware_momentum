# QA report — 1.52.21

Date: 2026-07-09  
Scope: `partial-mark-index-kline-validation`

## Baseline before code changes

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 9.99s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Red evidence

The new regression was added before changing `app/services/market_data.py`.

Command:

```bash
python -m pytest -q tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows
```

Result on unpatched 1.52.20 code:

```text
FAILED tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows - Failed: DID NOT RAISE <class 'ValueError'>
1 failed in 2.98s
```

This proved that a mark/index kline row containing `volume` but missing paired `turnover` passed normalization and could become a persisted candle fact with synthetic zero turnover.

## Green evidence

New regression:

```bash
python -m pytest -q tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows
```

```text
1 passed in 2.59s
```

Related candle validation subset:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_still_reject_last_klines_missing_volume_turnover \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_invalid_ohlcv_rows_before_persistence
```

```text
4 passed in 2.74s
```

## Post-check after code and documentation updates

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 8.06s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| Targeted new regression | PASSED | `1 passed in 2.59s` |
| Related candle subset | PASSED | `4 passed in 2.74s` |
| Forbidden exchange write endpoint grep in `app scripts web` | PASSED | no matches |
| `python scripts/release_integrity.py --write` | PASSED | `SHA256 manifest written`; `Release integrity PASSED: 290 files checked, 290 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 290 files checked, 290 manifest entries.` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Unverified in this sandbox

- Full pytest collection and PostgreSQL integration tests require installed `psycopg` and a safe PostgreSQL test database.
- `ruff` static analysis requires the missing `ruff` package.
- `pip check` remains blocked by an unrelated sandbox-level `moviepy`/`pillow` dependency conflict.
- Real Bybit paper/shadow/forward evidence was not run.
