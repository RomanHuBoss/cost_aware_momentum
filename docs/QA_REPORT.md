# QA report — 1.52.13

Date: 2026-07-09  
Scope: `exchange-cap-status`

## Baseline before code changes

| Command | Status | Exact result / note |
|---|---:|---|
| `python3 --version` | PASSED | `Python 3.13.5` |
| `python3 -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python3 -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python3 -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python3: No module named ruff` |
| `python3 -m pytest -q` | FAILED | collection interrupted: `62 errors in 15.20s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python3 scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 272 files checked, 272 manifest entries.` |
| `python3 scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 272 files checked, 272 manifest entries.` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox; `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Red evidence

Command:

```bash
python3 -m pytest -q \
  tests/unit/test_risk_math.py::test_exchange_cap_block_is_not_reported_as_min_order \
  tests/unit/test_risk_math.py::test_exchange_cap_limited_plan_has_operator_warning
```

Result on the unpatched code after adding the regression tests:

```text
FF [100%]
AssertionError: assert 'BLOCKED_MIN_SIZE' == 'BLOCKED_EXCHANGE'
assert False  # missing exchange-limit warning
2 failed in 0.42s
```

## Post-check after patch

| Command | Status | Exact result / note |
|---|---:|---|
| `python3 -m pip check` | FAILED | same environment conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python3 -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python3 -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python3: No module named ruff` |
| targeted regression pytest | PASSED | `32 passed in 4.51s` |
| `python3 -m pytest -q` | FAILED | collection interrupted: `62 errors in 13.79s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox; `psycopg` missing |

Targeted regression command:

```bash
python3 -m pytest -q \
  tests/unit/test_risk_math.py \
  tests/unit/test_candidate_live_attrition_report_2026_07_05.py::test_execution_plan_evidence_is_machine_readable_and_single_terminal \
  tests/unit/test_candidate_live_attrition_report_2026_07_05.py::test_exchange_block_is_risk_execution_attrition
```

Post targeted counts: passed 32 / failed 0 / skipped 0 / xfailed 0 / errors 0.

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Not verified in this sandbox

- Ruff static analysis, because `ruff` is not installed.
- Full pytest suite, because collection imports PostgreSQL engine paths and `psycopg` is not installed.
- PostgreSQL integration tests and `doctor`, because no safe PostgreSQL test database was provided.
- Live/paper/shadow Bybit connectivity.
- Model-training, activation, and drift-monitoring end-to-end flows.
