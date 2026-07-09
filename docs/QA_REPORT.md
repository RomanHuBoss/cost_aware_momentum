# QA report — 1.52.15

Date: 2026-07-09  
Scope: `bybit-list-payload-validation`

## Baseline before code changes

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | collection interrupted: `62 errors in 9.35s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 278 files checked, 278 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 278 files checked, 278 manifest entries.` |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Red evidence

Command:

```bash
python -m pytest -q tests/unit/test_bybit_response_contract_2026_07_09.py
```

Result on the unpatched code after adding the regression test:

```text
FFF [100%]
Failed: DID NOT RAISE <class 'RuntimeError'>
Failed: DID NOT RAISE <class 'RuntimeError'>
Failed: DID NOT RAISE <class 'RuntimeError'>
3 failed in 0.55s
```

## Green evidence

Targeted regression command:

```bash
python -m pytest -q tests/unit/test_bybit_response_contract_2026_07_09.py
```

Result after patch:

```text
... [100%]
3 passed in 0.41s
```

Related Bybit/client contract command:

```bash
python -m pytest -q \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_execution_exchange_integrity_2026_07_01.py \
  tests/unit/test_market_context_features_2026_07_05.py::test_open_interest_client_supports_bounded_historical_queries
```

Result after patch:

```text
........ [100%]
8 passed in 2.79s
```

## Post-check after patch

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | FAILED | same environment conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q tests/unit/test_bybit_response_contract_2026_07_09.py` | PASSED | `3 passed in 0.41s` |
| related Bybit/client contract pytest | PASSED | `8 passed in 2.79s` |
| `python -m pytest -q` | FAILED | collection interrupted: `62 errors in 6.77s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| order create/amend/cancel/withdraw endpoint grep in `app scripts web` | PASSED | no forbidden endpoints found |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 278 files checked, 278 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 278 files checked, 278 manifest entries.` |

Post targeted counts: passed 8 / failed 0 / skipped 0 / xfailed 0 / errors 0.

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Not verified in this sandbox

- Ruff static analysis, because `ruff` is not installed.
- Full pytest suite, because collection imports PostgreSQL engine paths and `psycopg` is not installed.
- PostgreSQL integration tests and `doctor`, because no safe PostgreSQL test database was provided.
- Live/paper/shadow Bybit connectivity.
- Model-training, activation, and drift-monitoring end-to-end flows.
