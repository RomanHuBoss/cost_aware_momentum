# Iteration report — 2026-07-09 — mark-index-kline-volume

## 1. Input archive, SHA-256, versions

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `e1102eae08b86a17129e50a508ba5604c857f566dcc36dd2633535db333c24e5`
- Source version: `1.52.18`
- Output version: `1.52.19`
- Version type: patch
- Project root detected after extraction: `cost_aware_momentum-main/`
- Python requirement from `pyproject.toml`: `>=3.12`
- Runtime Python in sandbox: `Python 3.13.5`
- Alembic head: `0018_inference_observations (head)`
- Production files: 122 under `app`, `scripts`, `web`, and `migrations`
- Test files: 127 under `tests`
- Documentation files after this iteration: 17 under `docs`
- Unexpected release artifacts in the source tree before baseline: runtime placeholder directories only: `backups/.gitkeep`, `models/.gitkeep`, `reports/.gitkeep`. Cache files were created by local checks and removed before packaging.

## 2. Trigger and scope selection

The user provided live logs showing repeated market-data validation failures:

```text
ValueError: Bybit kline row is incomplete: missing kline.volume
logger: app.services.market_data
event: candle_validation_failed
symbols: XLMUSDT, XMRUSDT, XPLUSDT
```

This became the iteration scope. The system already validates ordinary OHLCV candles strictly, but `sync_candles()` also requests `price_types=("last", "mark", "index")` when mark/index synchronization is enabled. Official Bybit docs define ordinary `/v5/market/kline` rows as seven fields including `volume` and `turnover`, while `/v5/market/mark-price-kline` and `/v5/market/index-price-kline` rows contain only `startTime`, `openPrice`, `highPrice`, `lowPrice`, and `closePrice`.

## 3. Goal and acceptance criteria

Goal:

> After this iteration, valid Bybit mark/index price-only kline rows must be persisted without `missing kline.volume` failures, while ordinary last-trade klines must still fail closed when volume/turnover are absent or invalid.

Acceptance criteria:

1. `price_type="mark"` and `price_type="index"` accept five-field rows `[startTime, open, high, low, close]`.
2. Mark/index rows still reject invalid open/high/low/close values and inconsistent OHLC geometry.
3. Mark/index missing volume/turnover are represented explicitly as `Decimal("0")` because the shared `market.candles` schema has non-null `volume` and `turnover` columns.
4. `price_type="last"` still rejects five-field rows with `missing kline.volume`.
5. Existing candle integrity tests still pass.
6. No DB migration, `.env`, public API schema, or exchange endpoint expansion is introduced.
7. Advisory-only invariant remains unchanged.

## 4. Read sources and project/data-flow map

Read project sources:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.16.md`, `PATCH_1.52.17.md`, `PATCH_1.52.18.md`
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
- `app/db/models.py`
- relevant candle/market-data tests

External reference checked:

- Bybit V5 Get Kline documentation: ordinary kline response list includes `list[5]` volume and `list[6]` turnover.
- Bybit V5 Get Mark Price Kline documentation: response list has fields `list[0]` through `list[4]` only.
- Bybit V5 Get Index Price Kline documentation: response list has fields `list[0]` through `list[4]` only.

Project map relevant to this iteration:

- Bybit client: `app/bybit/client.py::BybitClient.get_kline()` routes `last`, `mark`, `index` to the correct public GET endpoints.
- Market-data ingestion: `app/services/market_data.py::sync_candles()` fetches pages per symbol and price type.
- Candle normalization: `app/services/market_data.py::_candle_values()` converts Bybit row arrays into DB values.
- Persistence: `app/services/market_data.py::_upsert_candle_values()` writes into `market.candles` with natural uniqueness on symbol/interval/open_time/price_type.
- Schema: `app/db/models.py::Candle` stores all price types in one non-null OHLCV table.
- Downstream consumers: ML features and signal context use `last`, `mark`, and `index` candle price series; mark/index volume/turnover must not be interpreted as traded volume.

## 5. Baseline results

Baseline commands were run before production-code changes.

| Command | Status | Result |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 8.64s`, all observed collection failures rooted in `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL and missing `psycopg` |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL and missing `psycopg` |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## 6. Confirmed defect

### Valid mark/index price-only klines were rejected as incomplete ordinary OHLCV rows

- Type: CONFIRMED DEFECT
- Severity: high
- Files: `app/services/market_data.py`, `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py`
- Functions: `_validated_candle_ohlcv()`, `_candle_values()`, `sync_candles()`, `sync_candle_history()`
- Path: Bybit public mark/index kline endpoint -> `BybitClient.get_kline(..., price_type="mark"|"index")` -> `sync_candles()` or `sync_candle_history()` -> `_candle_values()` -> `_validated_candle_ohlcv()`
- Actual behavior: all price types required `row[5]` volume and `row[6]` turnover.
- Expected behavior: ordinary last-trade klines require OHLCV; mark/index klines are price-only and must not be rejected only because volume/turnover are absent.
- Financial/model impact: valid mark/index candle data can be missed, producing stale/missing basis evidence for model features, signal context, and operational diagnostics.
- Operational impact: worker logs repeated `candle_validation_failed` errors and counts otherwise valid requests as failed.
- Why existing tests did not catch it: the existing mark-price history test used a seven-field fixture, masking the true five-field exchange response shape.
- Reproduction: call `_candle_values(price_type="mark", rows=[[open_ms,"100","101","99","100.5"]])` on 1.52.18.
- Future test: `test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover`.

## 7. Red → green evidence

Red command after adding the regression and before implementation:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_still_reject_last_klines_missing_volume_turnover
```

Red result:

```text
F.                                                                       [100%]
FAILED tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover
ValueError: Bybit kline row is incomplete: missing kline.volume
1 failed, 1 passed in 3.02s
```

Green command after implementation:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_still_reject_last_klines_missing_volume_turnover
```

Green result:

```text
2 passed in 3.05s
```

Related subset:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py \
  tests/unit/test_intrahorizon_liquidation_mtm_2026_07_05.py::test_progressive_history_backfill_persists_explicit_mark_price_type
```

Result:

```text
13 passed in 2.69s
```

## 8. Implementation diff by file

Production:

- `app/services/market_data.py`
  - `_validated_candle_ohlcv()` now accepts `price_type`.
  - `last` rows still require volume/turnover.
  - `mark` and `index` rows accept documented five-field price-only payloads and store explicit zero placeholders for missing volume/turnover.
  - If optional extra volume/turnover fields exist on mark/index rows, they are still validated as finite non-negative decimals.

Tests:

- `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py`
  - Added mark/index five-field acceptance regression.
  - Added ordinary last-trade missing-volume rejection regression.

Docs/release:

- `pyproject.toml`
- `app/__init__.py`
- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.19.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/SECURITY.md`
- `docs/OPERATOR_MANUAL.md`
- `docs/CONFIGURATION.md`
- `docs/MODEL_CARD.md`
- `docs/ITERATION_REPORT_2026-07-09_mark-index-kline-volume.md`
- `SHA256SUMS`

## 9. Migrations, API/config/env compatibility

- New Alembic migration: none.
- Alembic head remains `0018_inference_observations`.
- Public API schema changes: none.
- `.env.example` changes: none.
- New environment variables: none.
- Bybit endpoint set: unchanged.
- Advisory-only invariant: unchanged. No order create/amend/cancel/withdraw capability was added.

## 10. Post-check results

| Command | Status | Result |
|---|---:|---|
| `python -m pip check` | FAILED | same sandbox conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| new mark/index regressions | PASSED | `2 passed in 3.05s` |
| candle/mark-index subset | PASSED | `13 passed in 2.69s` |
| `python -m pytest -q` | FAILED | `62 errors in 7.18s`, representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |

Full pytest counts after patch: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## 11. Additional release checks

- Release cache cleanup: removed `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `*.pyc`, `*.pyo` before final packaging.
- Forbidden exchange write endpoint grep in `app scripts web`: no order create/amend/cancel/withdraw endpoints found.
- `python scripts/release_integrity.py --write`: passed and regenerated `SHA256SUMS`.
- `python scripts/release_integrity.py`: passed.
- Final ZIP test with `unzip -t`: passed.
- Final ZIP was re-extracted into a clean directory and release integrity passed there.

## 12. What could not be verified

- Full pytest suite because sandbox lacks `psycopg`.
- PostgreSQL integration tests because no safe local PostgreSQL test instance was configured.
- `manage.py doctor` because no safe local PostgreSQL runtime config was available and `psycopg` is missing.
- Ruff static analysis because `ruff` is not installed in this sandbox.
- Clean `pip check` because of an unrelated global sandbox `moviepy`/`pillow` conflict.
- Live Bybit smoke run was not performed; this patch is validated by official payload contract and deterministic unit tests.

## 13. Residual risks and limitations

- The shared `market.candles` table cannot distinguish structurally unavailable mark/index volume from true zero volume except by `price_type`; downstream code must not treat mark/index volume/turnover as traded volume.
- Historical rows previously missed because of this bug require rerunning mark/index sync/backfill to populate.
- Full DB-backed behavior still requires verification in the operator's real development/test environment with PostgreSQL and project dependencies installed.

## 14. Rollback procedure

1. Revert `app/services/market_data.py` and `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py` to version `1.52.18`.
2. Restore version markers in `pyproject.toml`, `app/__init__.py`, and `README.md` to `1.52.18`.
3. Remove `PATCH_1.52.19.md` and this iteration report.
4. Restore docs changed for 1.52.19 or rerun release documentation from the previous archive.
5. Run `python scripts/release_integrity.py --write` and then `python scripts/release_integrity.py` after rollback.

## 15. Recommended next work package

P1/P2: add a diagnostic counter split by `price_type` and `validation_error_code` for candle sync/backfill. This would let the operator see whether failures are last-trade OHLCV defects, mark/index price defects, fetch errors, stale coverage, or DB persistence failures without reading raw logs.
