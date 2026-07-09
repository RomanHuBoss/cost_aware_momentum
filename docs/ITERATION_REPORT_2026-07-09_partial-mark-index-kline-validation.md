# Iteration report — 2026-07-09 — partial-mark-index-kline-validation

## Input archive, SHA-256, source version

- Input archive: `cost_aware_momentum-main(1).zip`
- Input SHA-256: `028ac9f108896cd20de863272616c051b3a47e88f1f6407a4f417371be0885bf`
- Source version: `1.52.20`
- New version: `1.52.21`
- Python requirement: `>=3.12`
- Package: `cost-aware-momentum`
- Alembic head at baseline: `0018_inference_observations (head)`
- ZIP root: `cost_aware_momentum-main/`

Baseline input ZIP counts: 289 files; production/app/scripts/manage Python files 99; test files 127; documentation/release files 28; migration files 20; web files 4. The input ZIP contained no `.env`, virtualenv, pycache, pytest cache, bytecode, build/dist, model blobs, dumps, or runtime backup/report files. Existing release artifacts in the input root: `Crypto Trading System Iteration Report.pdf` and `SHA256SUMS`.

## Goal and acceptance criteria

Goal: after this iteration, Bybit mark/index kline ingestion must accept the documented price-only five-field payload shape, validate optional volume/turnover only when both are present, and fail closed on partial OHLCV-like rows before they can be persisted as candle market facts.

Acceptance criteria:

1. Five-field mark/index price-only rows still produce explicit zero volume/turnover placeholders for the shared non-null candle schema.
2. Partial mark/index rows with `volume` present but `turnover` missing fail closed.
3. Ordinary `last` candle rows still reject missing volume/turnover.
4. Invalid OHLCV geometry and non-finite/negative ordinary fields still fail closed.
5. Advisory-only, PostgreSQL-only, API schema, `.env`, and Alembic migration contracts remain unchanged.
6. Documentation, traceability, QA report, and release version evidence are synchronized.

## Sources read and data flow

Read sources:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.17.md` through `PATCH_1.52.20.md`
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
- `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py`
- `tests/unit/test_bybit_response_contract_2026_07_09.py`

Relevant data flow:

1. `BybitClient.get_kline()` fetches read-only Bybit kline payloads for `last`, `mark`, or `index` price types.
2. `sync_candles()` receives rows and calls `_candle_values()`.
3. `_candle_values()` converts exchange rows into candle persistence dictionaries and delegates OHLCV validation to `_validated_candle_ohlcv()`.
4. `_validated_candle_ohlcv()` enforces positive finite OHLC prices, consistent OHLC geometry, and price-type-specific volume/turnover semantics.
5. `_upsert_candle_values()` persists validated rows into PostgreSQL candle state.

## Baseline commands and exact results

| Command | Status | Result |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 9.99s`; representative: `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Confirmed defects/gaps with severity, files, and evidence

### DEF-1 — partial mark/index OHLCV-like rows accepted with synthetic paired turnover

- Type: CONFIRMED DEFECT
- Severity: medium
- File: `app/services/market_data.py`
- Function: `_validated_candle_ohlcv()`
- Downstream path: `BybitClient.get_kline()` -> `sync_candles()` -> `_candle_values()` -> `_validated_candle_ohlcv()` -> `_upsert_candle_values()` -> `market.candles`
- Actual behavior: for `price_type in {"mark", "index"}`, a row with six fields `[start, open, high, low, close, volume]` was accepted; `volume` was validated from the row and `turnover` was silently set to `Decimal("0")`.
- Expected behavior: mark/index rows should either be documented price-only rows with both volume and turnover absent, or rows with both optional fields present and validated. A partial row must fail closed.
- Impact: downstream candle facts could combine an exchange-provided volume with a synthetic zero turnover placeholder. That creates ambiguous market data and can contaminate point-in-time features, backfill quality diagnostics, and operator confidence in candle ingestion.
- Why existing tests missed it: existing coverage tested five-field mark/index price-only rows and ordinary last-trade missing-volume rejection, but did not cover the equality boundary between “both optional fields absent” and “both optional fields present”.
- Reproduction: run the red regression listed below against the unpatched `1.52.20` code.
- Future test: `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows`.

## Plan and actual diff by file

Production:

- `app/services/market_data.py`
  - Changed mark/index optional volume/turnover handling so five-field rows get explicit zero placeholders, seven-or-more-field rows validate both optional fields, and six-field partial rows raise `ValueError`.
- `app/__init__.py`
  - Version bumped to `1.52.21`.
- `pyproject.toml`
  - Version bumped to `1.52.21`.

Tests:

- `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py`
  - Added `test_candle_values_reject_partial_mark_index_ohlcv_rows`.

Docs/release:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.21.md`
- `docs/QA_REPORT.md`
- `docs/SECURITY.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/CONFIGURATION.md`
- `docs/OPERATOR_MANUAL.md`
- `docs/ITERATION_REPORT_2026-07-09_partial-mark-index-kline-validation.md`
- `SHA256SUMS`

Migrations: no migration files changed.

## Red -> green evidence

Red command before fix:

```bash
python -m pytest -q tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows
```

Red result:

```text
FAILED tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows - Failed: DID NOT RAISE <class 'ValueError'>
1 failed in 2.98s
```

Green command after fix:

```bash
python -m pytest -q tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows
```

Green result:

```text
1 passed in 2.59s
```

Related subset:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_still_reject_last_klines_missing_volume_turnover \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_invalid_ohlcv_rows_before_persistence
```

```text
4 passed in 2.74s
```

## Migrations, API/config/env compatibility

- Alembic migration: none.
- Alembic head remains `0018_inference_observations (head)`.
- API schema changes: none.
- `.env` changes: none.
- Bybit endpoint changes: none.
- Advisory-only status: preserved; no order create/amend/cancel/withdraw methods or endpoints added.
- PostgreSQL-only status: preserved; no SQLite fallback added.

## Post-check commands and exact results

| Command | Status | Result |
|---|---:|---|
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 8.06s`; representative: `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| Targeted new regression | PASSED | `1 passed in 2.59s` |
| Related candle subset | PASSED | `4 passed in 2.74s` |
| Forbidden exchange write endpoint grep in `app scripts web` | PASSED | no matches |
| `python scripts/release_integrity.py --write` | PASSED | `SHA256 manifest written`; `Release integrity PASSED: 290 files checked, 290 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 290 files checked, 290 manifest entries.` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## What could not be verified and why

- Full pytest collection could not complete because the sandbox does not have `psycopg` installed.
- PostgreSQL integration tests and `manage.py doctor` were not run because there is no safe configured PostgreSQL test instance and `psycopg` is missing.
- `ruff` static analysis was unavailable because `ruff` is not installed in the sandbox.
- `python -m pip check` remains blocked by an unrelated sandbox-level `moviepy`/`pillow` conflict.
- No real Bybit paper/shadow/forward cycle was run.

## Residual risks and limitations

- This iteration covers one confirmed market-data validation defect, not all possible kline, feature, execution, ML-validation, or lifecycle risks.
- Runtime behavior under live Bybit anomalies still requires paper/shadow evidence with read-only credentials and PostgreSQL.
- Existing full-suite health remains unproven in this sandbox until dependencies and a safe PostgreSQL test database are available.

## Rollback procedure

1. Revert `app/services/market_data.py` to the `1.52.20` implementation.
2. Remove `test_candle_values_reject_partial_mark_index_ohlcv_rows` from `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py`.
3. Revert version strings in `pyproject.toml` and `app/__init__.py` to `1.52.20`.
4. Remove `PATCH_1.52.21.md` and this iteration report.
5. Revert documentation entries in README, CHANGELOG, QA, SECURITY, SPEC_COMPLIANCE, TRACEABILITY, CONFIGURATION, and OPERATOR_MANUAL.
6. Re-run the targeted candle subset and release integrity checks.

## Recommended next work package

Next recommended work package: install the declared dev/runtime dependencies in a clean PostgreSQL-backed environment and execute the full pytest suite plus `python manage.py doctor` / `python manage.py test --require-integration`, because current sandbox verification is still blocked at collection by missing `psycopg`.
