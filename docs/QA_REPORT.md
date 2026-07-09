# QA report — 1.52.18

Date: 2026-07-09  
Scope: `candle-ohlcv-validation`

## Baseline before code changes

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 8.45s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Red evidence

The new regression was added before the implementation change and run against the unpatched 1.52.17 implementation.

Command:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_invalid_ohlcv_rows_before_persistence -q
```

Result on unpatched code:

```text
FAILED tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_invalid_ohlcv_rows_before_persistence
Failed: DID NOT RAISE <class 'ValueError'>
```

This proved that `_candle_values()` accepted inconsistent OHLC geometry before the fix.

## Green evidence

New regression command:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_invalid_ohlcv_rows_before_persistence \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_sync_candles_reports_malformed_ohlcv_without_persisting
```

Result after patch:

```text
2 passed in 3.14s
```

Related candle/market-data regression subset:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py \
  tests/unit/test_candle_availability_integrity_2026_07_03.py \
  tests/unit/test_initial_training_backfill_readiness_2026_07_08.py \
  tests/unit/test_intrabar_outcomes.py \
  tests/unit/test_intrahorizon_liquidation_mtm_2026_07_05.py
```

Result after patch:

```text
31 passed in 3.16s
```

Broader PostgreSQL-free risk/client/market-data subset:

```bash
python -m pytest -q \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_orderbook_execution_quality_2026_07_05.py \
  tests/unit/test_risk_math.py
```

Result after patch:

```text
80 passed in 3.49s
```

Post targeted counts: passed 111 / failed 0 / skipped 0 / xfailed 0 / errors 0.

## Post-check after patch

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | FAILED | same environment conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| new candle regressions | PASSED | `2 passed in 3.14s` |
| candle/market-data subset | PASSED | `31 passed in 3.16s` |
| PostgreSQL-free risk/client/market-data subset | PASSED | `80 passed in 3.49s` |
| `python -m pytest -q` | FAILED | `62 errors in 8.45s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| order create/amend/cancel/withdraw endpoint grep in `app scripts web` | PASSED | no forbidden endpoint strings found |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 284 files checked, 284 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 284 files checked, 284 manifest entries.` |

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Not verified in this sandbox

- Ruff static analysis, because `ruff` is not installed.
- Full pytest suite, because collection imports PostgreSQL engine paths and `psycopg` is not installed.
- PostgreSQL integration tests and `doctor`, because no safe PostgreSQL test database was provided.
- Live/paper/shadow Bybit connectivity.
- Model-training, activation, and drift-monitoring end-to-end flows.
