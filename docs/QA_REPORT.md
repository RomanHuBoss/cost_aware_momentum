# QA report — 1.52.23

Date: 2026-07-10  
Scope: `locked-ticker-validation`

## Baseline before code changes

The host Python environment was incomplete for this project, so its failures were recorded rather than hidden. A clean temporary project virtual environment was then created from `.[dev]`; all source-code baseline checks below were run before production code was changed.

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
| `python --version` | PASSED | `Python 3.13.5`; project requires Python `>=3.12` |
| `python -m pip check` | PASSED | `No broken requirements found.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | PASSED | `All checks passed!` |
| `python -m pytest -q` | PASSED | `905 passed, 8 skipped in 18.48s` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in the sandbox |
| `python manage.py test --require-integration` | SKIPPED | `TEST_DATABASE_URL` was not configured; integration tests were not pointed at an unknown database |

Baseline counts in the isolated project environment: passed 905 / failed 0 / skipped 8 / xfailed 0 / errors 0. All eight skips were PostgreSQL integration cases requiring `TEST_DATABASE_URL`.

## Red evidence

Four regressions were added before production code was changed.

```bash
python -m pytest -q \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_signal_policy_rejects_locked_quote \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_acceptance_rejects_locked_quote \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_dynamic_universe_rejects_locked_quote \
  tests/unit/test_quote_plan_contract_2026_06_30.py::test_ticker_sync_drops_locked_bid_ask
```

Unpatched 1.52.22 result:

```text
FAILED ...::test_signal_policy_rejects_locked_quote - Failed: DID NOT RAISE <class 'ValueError'>
FAILED ...::test_acceptance_rejects_locked_quote - Failed: DID NOT RAISE <class 'ValueError'>
FAILED ...::test_dynamic_universe_rejects_locked_quote - assert ('LOCKEDUSDT',) == ()
FAILED ...::test_ticker_sync_drops_locked_bid_ask - assert Decimal('100') is None
4 failed in 3.06s
```

## Green evidence

After the minimal production fix:

```text
4 passed in 2.75s
```

Related signal, acceptance, universe, and orderbook subset:

```text
79 passed in 3.68s
```

Six pre-existing geometry tests used `bid == ask == 100` as a synthetic no-cost quote. The full suite correctly exposed that those fixtures violated the new executable-quote invariant. They were changed to valid, strictly positive, tick-aligned spreads while preserving their original timeout/barrier/tick-rounding assertions. The aligned regression subset then passed:

```text
8 passed in 3.12s
```

## Post-check after code, tests, version, and documentation updates

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | PASSED | `No broken requirements found.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | PASSED | `All checks passed!` |
| `python -m pytest -q` | PASSED | `909 passed, 8 skipped in 14.83s` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| New locked-ticker regressions | PASSED | `4 passed in 2.75s` |
| Related signal/acceptance/universe/orderbook subset | PASSED | `79 passed in 3.68s` |
| Forbidden exchange write endpoint grep in `app scripts web` | PASSED | no Bybit order create/amend/cancel or withdrawal implementation found |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance |
| `python manage.py test --require-integration` | SKIPPED | no `TEST_DATABASE_URL` |

Post-check counts: passed 909 / failed 0 / skipped 8 / xfailed 0 / errors 0. All eight skips are PostgreSQL integration tests and explicitly report `TEST_DATABASE_URL is not configured`.

Release-integrity, archive test, clean re-extraction, and final SHA-256 are recorded in `docs/ITERATION_REPORT_2026-07-10_locked-ticker-validation.md` after final packaging.

## Unverified in this sandbox

- PostgreSQL migration upgrade/downgrade and integration behavior were not executed because no safe test database was configured.
- `python manage.py doctor` was not run against a real local deployment.
- Exact Python 3.12 execution was unavailable; checks used Python 3.13.5, which satisfies the declared `>=3.12` requirement.
- Real Bybit paper/shadow/forward behavior and live exchange anomalies were not exercised.
- No claim of strategy profitability or live edge is made.
