# QA report — 1.52.14

Date: 2026-07-09  
Scope: `validated-cash-inputs`

## Baseline before code changes

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | collection interrupted: `62 errors in 8.76s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Red evidence

Command:

```bash
python -m pytest -q \
  tests/unit/test_risk_math.py::test_funding_cash_flow_rejects_negative_position_value \
  tests/unit/test_risk_math.py::test_fee_cash_rejects_negative_fee_rate
```

Result on the unpatched code after adding the regression tests:

```text
FF [100%]
Failed: DID NOT RAISE <class 'ValueError'>
Failed: DID NOT RAISE <class 'ValueError'>
2 failed in 0.28s
```

## Green evidence

Targeted regression command:

```bash
python -m pytest -q \
  tests/unit/test_risk_math.py::test_funding_cash_flow_rejects_negative_position_value \
  tests/unit/test_risk_math.py::test_fee_cash_rejects_negative_fee_rate
```

Result after patch:

```text
.. [100%]
2 passed in 0.11s
```

Full pure risk-math command:

```bash
python -m pytest -q tests/unit/test_risk_math.py
```

Result after patch:

```text
................................ [100%]
32 passed in 0.16s
```

## Post-check after patch

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | FAILED | same environment conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| targeted regression pytest | PASSED | `2 passed in 0.11s` |
| `python -m pytest -q tests/unit/test_risk_math.py` | PASSED | `32 passed in 0.16s` |
| `python -m pytest -q` | FAILED | collection interrupted: `62 errors in 6.85s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 275 files checked, 275 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | run after cache cleanup; `Release integrity PASSED: 275 files checked, 275 manifest entries.` |

Post targeted counts: passed 32 / failed 0 / skipped 0 / xfailed 0 / errors 0.

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Not verified in this sandbox

- Ruff static analysis, because `ruff` is not installed.
- Full pytest suite, because collection imports PostgreSQL engine paths and `psycopg` is not installed.
- PostgreSQL integration tests and `doctor`, because no safe PostgreSQL test database was provided.
- Live/paper/shadow Bybit connectivity.
- Model-training, activation, and drift-monitoring end-to-end flows.
