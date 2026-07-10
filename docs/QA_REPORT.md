# QA report — 1.52.24

Date: 2026-07-10  
Scope: `operator-surface-auth`

## Baseline before code changes

The host Python environment was incomplete for this project. Its failures were recorded rather than hidden. A clean temporary project virtual environment was installed from `.[dev]`, and the isolated baseline completed before production code changes.

### Host environment preflight

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | unrelated host conflict: `moviepy 2.2.1` requires `pillow<12.0`, host had `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | host interpreter had no `ruff` module |
| `python -m pytest -q` | FAILED | collection stopped with `62 errors`; representative cause `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |

### Isolated project environment baseline

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5`; project requires `>=3.12` |
| `python -m pip check` | PASSED | `No broken requirements found.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | PASSED | `All checks passed!` |
| `python -m pytest -q` | PASSED | `909 passed, 8 skipped in 24.37s` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | one head: `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL deployment in the sandbox |
| `python manage.py test --require-integration` | SKIPPED | `TEST_DATABASE_URL` was not configured |

Baseline counts: passed 909 / failed 0 / skipped 8 / xfailed 0 / errors 0. The eight skips are PostgreSQL integration cases.

## Red evidence

Five tests were added in `tests/unit/test_operator_surface_security_2026_07_10.py` before production changes:

```bash
python -m pytest -q tests/unit/test_operator_surface_security_2026_07_10.py
```

Unpatched 1.52.23 result:

```text
FAILED test_sensitive_financial_read_endpoints_require_operator_authentication
FAILED test_operational_status_endpoints_require_operator_authentication
FAILED test_outbox_event_stream_requires_operator_authentication
FAILED test_production_requires_secure_authentication_cookies
FAILED test_logout_requires_authenticated_csrf_protection
5 failed in 6.30s
```

The route failures showed only storage/settings dependencies or no dependencies; production settings did not raise for `COOKIE_SECURE=false`; logout had no `require_csrf` dependency.

## Green evidence

After the minimal patch:

```text
5 passed in 6.44s
```

The full suite initially found one pre-existing test that directly called the newly protected `portfolio_risk()` handler without FastAPI dependency injection. That test was updated to pass a synthetic authenticated operator value; production authentication was not weakened.

Current full-suite result before final packaging:

```text
914 passed, 8 skipped in 22.21s
```

## Post-check

Final exact command results are recorded in `docs/ITERATION_REPORT_2026-07-10_operator-surface-auth.md`. Release integrity passed for 298 files, `unzip -t` passed, and clean re-extraction produced exactly one root with a second passing integrity check. PostgreSQL integration, real TLS, and live reverse-proxy/session behavior remain explicitly unverified.
