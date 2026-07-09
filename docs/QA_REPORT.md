# QA report — 1.52.19

Date: 2026-07-09  
Scope: `mark-index-kline-volume`

## Baseline before code changes

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 8.64s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Red evidence

The new regression was added before the implementation change and run against the unpatched 1.52.18 implementation.

Command:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_still_reject_last_klines_missing_volume_turnover
```

Result on unpatched code:

```text
F.                                                                       [100%]
FAILED tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover
ValueError: Bybit kline row is incomplete: missing kline.volume
1 failed, 1 passed in 3.02s
```

This proved that the previous implementation rejected documented five-field mark/index kline rows while still correctly rejecting last-trade klines missing volume/turnover.

## Green evidence

New regression command:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_still_reject_last_klines_missing_volume_turnover
```

Result after patch:

```text
2 passed in 3.05s
```

Related candle/mark-index subset:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py \
  tests/unit/test_intrahorizon_liquidation_mtm_2026_07_05.py::test_progressive_history_backfill_persists_explicit_mark_price_type
```

Result after patch:

```text
13 passed in 2.69s
```

Post targeted counts: passed 15 / failed 0 / skipped 0 / xfailed 0 / errors 0.

## Post-check after patch

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | FAILED | same sandbox dependency conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| new mark/index regressions | PASSED | `2 passed in 3.05s` |
| candle/mark-index subset | PASSED | `13 passed in 2.69s` |
| `python -m pytest -q` | FAILED | `62 errors in 7.18s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |

Full pytest counts after patch: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection, because this sandbox lacks `psycopg`.

## Not verified here

- PostgreSQL integration tests.
- `manage.py doctor` against a real local PostgreSQL configuration.
- `python -m ruff check .`, because ruff is not installed in the sandbox.
- `python -m pip check` clean status, because the global sandbox has an unrelated `moviepy`/`pillow` conflict.
