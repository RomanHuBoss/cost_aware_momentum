# QA report — 1.52.17

Date: 2026-07-09  
Scope: `wallet-account-contract`

## Baseline before code changes

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | collection interrupted: `62 errors in 12.09s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

A PostgreSQL-free control subset used to confirm the sandbox could execute unit tests passed before the wallet-account changes:

```bash
python -m pytest -q \
  tests/unit/test_risk_math.py \
  tests/unit/test_cost_aware_direction_selection.py \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_market_context_features_2026_07_05.py \
  tests/unit/test_point_in_time_funding_intervals_2026_07_05.py \
  tests/unit/test_labels_features.py \
  tests/unit/test_training_tick_geometry_alignment_2026_07_07.py
```

Result before patch:

```text
74 passed in 6.04s
```

## Red evidence

The new regression tests were copied into a clean extracted 1.52.16 tree and run against the unpatched implementation.

Command:

```bash
python -m pytest -q \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_wallet_without_coin_list_before_any_write \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_wallet_without_usdt_coin_before_any_write
```

Result on the unpatched code after adding the regression tests:

```text
5 failed, 17 passed in 5.46s
```

Representative failures:

```text
Failed: DID NOT RAISE <class 'RuntimeError'>
```

The failures covered:

- `get_wallet_balance()` accepting missing `wallet-balance.result.list`.
- `get_wallet_balance()` accepting `wallet-balance.result.list = None`.
- `get_wallet_balance()` accepting non-list `wallet-balance.result.list`.
- `sync_read_only_account()` accepting an account row with no `coin` array.
- `sync_read_only_account()` accepting an account row with no USDT coin row.

## Green evidence

Targeted regression command:

```bash
python -m pytest -q \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_malformed_open_position_before_any_write \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_missing_equity_before_persisting_snapshot \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_wallet_without_coin_list_before_any_write \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_wallet_without_usdt_coin_before_any_write \
  tests/unit/test_account_scope_integrity_2026_06_30.py::test_account_sync_stamps_positions_with_same_account_id \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_account_snapshot_time_is_after_wallet_and_position_reads
```

Result after patch:

```text
26 passed in 5.15s
```

PostgreSQL-free quant/client control subset:

```bash
python -m pytest -q \
  tests/unit/test_risk_math.py \
  tests/unit/test_cost_aware_direction_selection.py \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_market_context_features_2026_07_05.py \
  tests/unit/test_point_in_time_funding_intervals_2026_07_05.py \
  tests/unit/test_labels_features.py \
  tests/unit/test_training_tick_geometry_alignment_2026_07_07.py
```

Result after patch:

```text
77 passed in 6.21s
```

## Post-check after patch

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | FAILED | same environment conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| targeted wallet/account pytest | PASSED | `26 passed in 5.15s` |
| PostgreSQL-free quant/client control subset | PASSED | `77 passed in 6.21s` |
| `python -m pytest -q` | FAILED | collection interrupted: `62 errors in 12.06s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| order create/amend/cancel/withdraw endpoint grep in `app scripts web` | PASSED | no forbidden endpoint strings found |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 282 files checked, 282 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 282 files checked, 282 manifest entries.` |

Post targeted counts: passed 26 / failed 0 / skipped 0 / xfailed 0 / errors 0.

Post PostgreSQL-free control subset counts: passed 77 / failed 0 / skipped 0 / xfailed 0 / errors 0.

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Not verified in this sandbox

- Ruff static analysis, because `ruff` is not installed.
- Full pytest suite, because collection imports PostgreSQL engine paths and `psycopg` is not installed.
- PostgreSQL integration tests and `doctor`, because no safe PostgreSQL test database was provided.
- Live/paper/shadow Bybit connectivity.
- Model-training, activation, and drift-monitoring end-to-end flows.
