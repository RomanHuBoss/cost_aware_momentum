# QA report — 1.52.25

Date: 2026-07-11  
Scope: `transient-inference-retry`

## Baseline before code changes

### Host runtime

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.12.13` |
| `python -m pip check` | PASSED | `No broken requirements found.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | host runtime had no `ruff` module |
| `python -m pytest -q` | UNAVAILABLE | host runtime had no `pytest` module |
| `node --check web/js/app.js` | PASSED | exit 0 |

### Isolated project environment

The first raw isolated-suite run inherited a host SOCKS proxy and failed during `httpx.AsyncClient` construction because optional `socksio` was unavailable: `24 failed, 890 passed, 8 skipped`. With proxy variables removed for hermetic unit execution, the pre-change source baseline was:

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | PASSED | `No broken requirements found.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | `All checks passed!` |
| `python -m pytest -q` | PASSED | `914 passed, 8 skipped in 10.63s` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head: `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no deployment `.env` or safe PostgreSQL database |
| `python manage.py test --require-integration` | SKIPPED | no safe `TEST_DATABASE_URL` |

Controlled baseline counts: 914 passed / 0 failed / 8 skipped / 0 xfailed / 0 errors.

## Red evidence

The regression was added before the production change:

```bash
python -m pytest -q \
  tests/unit/test_inference_retry.py::test_complete_hourly_inference_retries_transient_market_data_skip
```

Unpatched 1.52.24 result:

```text
FAILED test_complete_hourly_inference_retries_transient_market_data_skip
AssertionError: assert False
1 failed in 1.60s
```

The failure proves that complete terminal coverage made `missing_decision_candle` non-retryable.

## Green evidence

After the minimal production fix:

```text
1 passed in 1.28s
```

Retry-contract file:

```text
6 passed in 1.23s
```

Related runner/scheduling/candle/ticker subset:

```text
26 passed in 1.40s
```

Intermediate full suite after code and test changes:

```text
917 passed, 8 skipped in 10.96s
```

## Post-check

Final dependency, compile, Ruff, pytest, JavaScript syntax, Alembic-head, version, forbidden endpoint/artifact, manifest, ZIP integrity, clean re-extraction, and changed-content checks were completed. Release integrity passed for 300 eligible files and 300 manifest entries; exact archive identity is provided in the final handoff.

Final non-integration counts: 917 passed / 0 failed / 8 skipped / 0 xfailed / 0 errors.

PostgreSQL integration tests, `manage.py doctor`, real Bybit forward delay/rate-limit behavior, and the user's deployed `JobRun`/log evidence were not available and are not claimed.
