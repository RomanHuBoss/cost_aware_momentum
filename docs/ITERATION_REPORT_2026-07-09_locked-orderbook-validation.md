# Iteration report — 2026-07-09 — locked-orderbook-validation

## Input archive, SHA-256, source version

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `7ad287c2c3af6477754ddc63180d57a55195c69494522aeeeae9757383c0da2a`
- Source version: `1.52.19`
- New version: `1.52.20`
- Python requirement: `>=3.12`
- Package: `cost-aware-momentum`
- Alembic head at baseline: `0018_inference_observations (head)`
- ZIP root: `cost_aware_momentum-main/`

Baseline source-tree counts before generated test caches: ZIP files 287; production files 238; test files 379; documentation/release files 30. Input ZIP contained no `.env`, virtualenv, pycache, pytest cache, bytecode, build/dist, model blobs, dumps, or runtime backup/report files. The input ZIP did include the existing root `Crypto Trading System Iteration Report.pdf` and `SHA256SUMS` release manifest.

## Goal and acceptance criteria

Goal: after this iteration, orderbook/liquidity evidence must fail closed when the top of book is locked (`best_ask == best_bid`) or crossed (`best_ask < best_bid`), before the snapshot can feed VWAP sizing, liquidity caps, execution evidence, or recommendation economics.

Acceptance criteria:

1. A locked top-of-book payload fails during orderbook normalization.
2. The existing crossed-book rejection remains intact.
3. Valid orderbook snapshots still normalize and persist through the existing contract.
4. Related VWAP/liquidity sizing tests still pass.
5. Advisory-only, PostgreSQL-only, API schema, `.env`, and Alembic migration contracts remain unchanged.
6. Documentation and release version evidence are synchronized.

## Sources read and data flow

Read sources:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.16.md` through `PATCH_1.52.19.md`
- `pyproject.toml`
- `.env.example`
- `docs/ARCHITECTURE.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/MODEL_CARD.md`
- `docs/CONFIGURATION.md`
- `docs/SECURITY.md`
- `docs/INCIDENT_RUNBOOK.md`
- `docs/OPERATOR_MANUAL.md`
- `app/bybit/client.py`
- `app/services/market_data.py`
- `app/risk/liquidity.py`
- `app/risk/math.py`
- `tests/unit/test_orderbook_execution_quality_2026_07_05.py`
- `tests/unit/test_orderbook_vwap_sizing_integrity_2026_07_08.py`

Relevant data flow:

1. `BybitClient.get_orderbook()` fetches read-only Bybit depth payloads.
2. `sync_orderbooks()` receives the payload and calls `normalize_orderbook_snapshot()`.
3. `normalize_orderbook_snapshot()` validates symbol, timestamps, update IDs, depth, bids, and asks.
4. `validate_orderbook_levels()` normalizes price/size levels and enforces top-of-book consistency.
5. Persisted `OrderBookSnapshot` data is later used by execution planning, VWAP sizing, liquidity caps, and diagnostics.

## Baseline commands and exact results

| Command | Status | Result |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 10.04s`; representative: `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Confirmed defects/gaps with severity, files, and evidence

### DEF-1 — locked top-of-book accepted as valid execution evidence

- Type: CONFIRMED DEFECT
- Severity: high
- File: `app/risk/liquidity.py`
- Function: `validate_orderbook_levels()`
- Downstream path: `BybitClient.get_orderbook()` -> `sync_orderbooks()` -> `normalize_orderbook_snapshot()` -> `validate_orderbook_levels()` -> `OrderBookSnapshot` -> VWAP sizing / liquidity caps / execution evidence
- Actual behavior: `best_ask == best_bid` was accepted because only `best_ask < best_bid` was rejected.
- Expected behavior: locked and crossed top-of-book states must both fail closed.
- Impact: a locked book can create a zero-spread execution snapshot and understate execution friction, which can make liquidity/economics evidence look more favorable than a conservative advisory system should allow.
- Why existing tests missed it: existing orderbook tests covered valid, crossed, malformed/sorted, and persistence paths, but did not include the equality boundary.
- Reproduction: run the red regression listed below against the unpatched code.
- Future test: `tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book`.

## Plan and actual diff by file

Production:

- `app/risk/liquidity.py`
  - Changed top-of-book invariant from `normalized_asks[0][0] < normalized_bids[0][0]` to `normalized_asks[0][0] <= normalized_bids[0][0]`.
  - Changed diagnostic to `orderbook is locked or crossed`.
- `app/__init__.py`
  - Version bumped to `1.52.20`.
- `pyproject.toml`
  - Version bumped to `1.52.20`.

Tests:

- `tests/unit/test_orderbook_execution_quality_2026_07_05.py`
  - Added locked top-of-book regression.

Docs/release:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.20.md`
- `docs/QA_REPORT.md`
- `docs/SECURITY.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/CONFIGURATION.md`
- `docs/ITERATION_REPORT_2026-07-09_locked-orderbook-validation.md`
- `SHA256SUMS`

Migrations: no migration files changed.

## Red -> green evidence

Red command before fix:

```bash
python -m pytest -q tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book
```

Red result:

```text
FAILED tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book - Failed: DID NOT RAISE <class 'ValueError'>
1 failed in 0.89s
```

Green command after fix:

```bash
python -m pytest -q \
  tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book \
  tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_uses_matching_engine_time_and_rejects_crossed_book
```

Green result:

```text
2 passed in 0.79s
```

Related subset:

```bash
python -m pytest -q tests/unit/test_orderbook_execution_quality_2026_07_05.py tests/unit/test_orderbook_vwap_sizing_integrity_2026_07_08.py
```

Result:

```text
19 passed in 2.64s
```

## Migrations, API/config/env compatibility

- Alembic migration: none.
- Alembic head remains `0018_inference_observations`.
- Public API schema: unchanged.
- `.env` variables: unchanged.
- Advisory-only Bybit client: unchanged; no order create/amend/cancel/withdraw methods added.
- PostgreSQL-only invariant: unchanged.

## Post-check commands and exact results

| Command | Status | Result |
|---|---:|---|
| `python -m pip check` | FAILED | same sandbox dependency conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book` | PASSED | `1 passed in 0.78s` |
| `python -m pytest -q tests/unit/test_orderbook_execution_quality_2026_07_05.py tests/unit/test_orderbook_vwap_sizing_integrity_2026_07_08.py` | PASSED | `19 passed in 2.64s` |
| `python -m pytest -q` | FAILED | `62 errors in 6.99s`; representative: `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |

Post-check targeted command counts: passed 20 / failed 0 / skipped 0 / xfailed 0 / errors 0. The related orderbook subset itself contains 19 unique passing tests.
Full pytest counts after patch: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## What could not be verified and why

- Full pytest suite: collection fails because this sandbox lacks `psycopg`.
- PostgreSQL integration tests: no safe configured PostgreSQL instance was available and `psycopg` is missing.
- `python manage.py doctor`: skipped for the same PostgreSQL/driver reason.
- `ruff`: unavailable in the sandbox.
- Clean `pip check`: blocked by an unrelated global sandbox dependency conflict between `moviepy` and `pillow`.

## Residual risks and limitations

- This iteration only hardens the locked/crossed orderbook boundary. It does not audit every execution, model, drift, or backtest path.
- No live profitability or production safety claim is made from these tests.
- A production verification pass still requires installing project dependencies, including `psycopg`, and running the full PostgreSQL-backed suite.

## Rollback procedure

1. Revert `app/risk/liquidity.py` to the previous `best_ask < best_bid` invariant only if a controlled exchange-specific analysis proves locked books are valid for this system.
2. Revert version/documentation files to `1.52.19`.
3. Re-run the orderbook tests and full suite in a properly provisioned PostgreSQL environment.

## Recommended next work package

Dependency/environment hardening: make the local test runner fail early with a clear diagnostic when required project dependencies such as `psycopg` or `ruff` are absent, and document the exact bootstrap command for a reproducible dev/test environment.
