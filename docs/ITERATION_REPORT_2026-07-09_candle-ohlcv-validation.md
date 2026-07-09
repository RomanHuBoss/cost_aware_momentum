# Iteration report — 2026-07-09 — candle-ohlcv-validation

## 1. Input archive, SHA-256, source version

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `a14bb72a9b1aca848249d75829b052e0b18f4f31984203ebf697b309030f7c0d`
- Source version: `1.52.17`
- New version: `1.52.18`
- Version type: patch
- Project root: `cost_aware_momentum-main`
- Python requirement: `>=3.12`; sandbox Python: `Python 3.13.5`
- Alembic head: `0018_inference_observations (head)`
- Baseline counts before modifications: production files 123, test files 127, documentation/Markdown/PDF files 23.
- Baseline unexpected artifacts after local checks generated caches: `__pycache__` and `.pytest_cache`; these were removed before final packaging.

## 2. Goal and acceptance criteria

Goal: after this iteration, Bybit kline/OHLCV rows must not persist impossible market facts, and malformed candle payloads must fail closed with diagnostics instead of being counted as successful persistence.

Acceptance criteria:

1. `_candle_values()` rejects inconsistent OHLC geometry.
2. `_candle_values()` rejects non-positive/non-finite OHLC prices.
3. `_candle_values()` rejects negative or non-finite volume/turnover.
4. `sync_candles()` does not call `_upsert_candle_values()` for malformed OHLCV rows.
5. `sync_candles()` reports malformed candle payloads as `requests_failed` diagnostics.
6. Existing candle, intrabar, orderbook, Bybit-response, and risk-math targeted regressions continue passing.
7. No migration, `.env`, public API schema, Bybit endpoint, or advisory-only behavior change is introduced.

## 3. Sources read and project map

Read sources:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.15.md`, `PATCH_1.52.16.md`, `PATCH_1.52.17.md`
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
- `app/services/market_data.py`
- `app/bybit/client.py`
- `app/risk/liquidity.py`
- `app/risk/math.py`
- relevant unit tests under `tests/unit/`

Project map used for scope selection:

- data ingestion / market data: `app/services/market_data.py`, `app/bybit/client.py`
- features / labels / training / validation / artifact lifecycle: `app/ml/*`
- inference / signals / execution plan: `app/services/signals.py`, `app/services/execution.py`
- risk/cost: `app/risk/math.py`, `app/risk/liquidity.py`
- account/profile logic: `app/services/market_data.py`, `app/services/market_snapshots.py`, `app/services/execution.py`
- API schemas/endpoints: `app/api/*`
- frontend: `web/js/app.js`
- ORM/migrations: `app/db/models.py`, `migrations/versions/*`
- audit/idempotency/outbox: `app/services/audit.py`, `app/services/idempotency.py`
- tests: `tests/unit/*`, `tests/integration_postgres/*`

## 4. Baseline commands and results

| Command | Status | Result |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1` requires `pillow<12.0`; installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | collection blocked by missing `psycopg`; later reproduced as `62 errors in 8.45s` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## 5. Confirmed defect

- Type: CONFIRMED DEFECT
- Severity: high
- Files: `app/services/market_data.py`, `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py`
- Function: `_candle_values()` and `sync_candles()`
- Data path: Bybit `/v5/market/kline` -> `BybitClient.get_kline()` -> `sync_candles()` / historical candle paths -> `_candle_values()` -> `market.candles`
- Actual behavior: `_candle_values()` accepted permissively parsed candle prices and defaulted missing volume/turnover to zero. A row with inconsistent OHLC geometry, negative volume, or non-finite turnover was not rejected before the persistence path.
- Expected behavior: invalid OHLCV rows must fail closed before they can become persisted market facts.
- Impact: impossible candle facts can contaminate features, labels, inference freshness, model validation, and backtest/report evidence.
- Why existing tests missed it: existing point-in-time candle tests checked availability timing and immutable upsert behavior, but not semantic OHLCV row invariants.
- Reproduction: add the red regression and pass a candle row where `high < close`, negative `volume`, or `turnover = NaN`.
- Future guard: `test_candle_values_reject_invalid_ohlcv_rows_before_persistence` and `test_sync_candles_reports_malformed_ohlcv_without_persisting`.

## 6. Plan and actual diff by file

Production files changed:

- `app/services/market_data.py`
  - Added `_required_candle_decimal()`.
  - Added `_validated_candle_ohlcv()`.
  - Replaced permissive candle Decimal parsing with strict OHLCV validation.
  - Wrapped `sync_candles()` validation/upsert in a failure-accounting block so malformed rows are counted as failed requests and not persisted.
- `app/__init__.py`
  - Version updated to `1.52.18`.
- `pyproject.toml`
  - Version updated to `1.52.18`.

Test files changed:

- `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py`
  - Added semantic OHLCV rejection regression.
  - Added `sync_candles()` no-persist/diagnostics regression.

Documentation/release files changed:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.18.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/CONFIGURATION.md`
- `docs/SECURITY.md`
- `docs/OPERATOR_MANUAL.md`
- `docs/ITERATION_REPORT_2026-07-09_candle-ohlcv-validation.md`
- `SHA256SUMS`

Migration files changed: none.

## 7. Red -> green evidence

Red command:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_invalid_ohlcv_rows_before_persistence -q
```

Red result on unpatched code:

```text
FAILED tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_invalid_ohlcv_rows_before_persistence
Failed: DID NOT RAISE <class 'ValueError'>
```

Green command:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_invalid_ohlcv_rows_before_persistence \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_sync_candles_reports_malformed_ohlcv_without_persisting
```

Green result:

```text
2 passed in 3.14s
```

## 8. Migrations, API/config/env compatibility

- Alembic migration: not required.
- Alembic head: `0018_inference_observations (head)`.
- Public API schema: unchanged.
- `.env.example`: unchanged.
- Database schema: unchanged.
- Bybit endpoint set: unchanged.
- Advisory-only invariant: preserved. No order create/amend/cancel/withdraw endpoint or method was added.

## 9. Post-check commands and results

| Command | Status | Result |
|---|---:|---|
| `python -m pip check` | FAILED | same sandbox dependency conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| new candle regressions | PASSED | `2 passed in 3.14s` |
| candle/market-data subset | PASSED | `31 passed in 3.16s` |
| PostgreSQL-free risk/client/market-data subset | PASSED | `80 passed in 3.49s` |
| `python -m pytest -q` | FAILED | `62 errors in 8.45s`; representative `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| forbidden order/withdraw endpoint grep in `app scripts web` | PASSED | no forbidden endpoint strings found |
| `python manage.py doctor` | SKIPPED | no safe PostgreSQL instance and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe PostgreSQL instance and `psycopg` missing |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 284 files checked, 284 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 284 files checked, 284 manifest entries.` |

Post targeted counts: passed 111 / failed 0 / skipped 0 / xfailed 0 / errors 0.

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## 10. Not verified and why

- Ruff static analysis: `ruff` is unavailable in this sandbox.
- Full pytest suite: collection imports `app.db.engine`, which requires `psycopg`; `psycopg` is unavailable in this sandbox.
- PostgreSQL integration tests and `manage.py doctor`: no safe configured PostgreSQL test database was provided and `psycopg` is unavailable.
- Live/paper/shadow Bybit connectivity: not exercised.
- End-to-end API/worker/trainer/model activation/drift-monitoring flows: not exercised.

## 11. Residual risks and limitations

- This patch validates candle row semantics, but does not independently validate every ticker/funding/open-interest row field.
- Full DB-backed confidence requires rerunning the complete suite with project dev dependencies and an isolated non-production PostgreSQL database.
- This patch does not prove live profitability, live edge, or model robustness.
- `sync_candles()` still treats empty valid exchange pages as non-failing no-data responses; current-hour coverage gates must catch missing required close times.

## 12. Rollback procedure

1. Revert `app/services/market_data.py` and `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py` to `1.52.17`.
2. Restore version metadata in `pyproject.toml`, `app/__init__.py`, and `README.md` to `1.52.17`.
3. Remove `PATCH_1.52.18.md` and this iteration report.
4. Restore `CHANGELOG.md`, docs files, and `SHA256SUMS` from the `1.52.17` archive or rerun `python scripts/release_integrity.py --write` after rollback.
5. No database downgrade is required because no migration was added.

## 13. Recommended next work package

Harden semantic validation of remaining Bybit market/account rows after list-shape validation: ticker row required fields and bid/ask consistency, funding timestamp/rate semantics, open-interest timestamp/value semantics, and explicit stale diagnostics for read-only account snapshots.
