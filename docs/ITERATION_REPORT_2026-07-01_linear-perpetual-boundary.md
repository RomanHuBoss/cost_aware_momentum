# Iteration report — linear perpetual boundary

## 1. Input and baseline identity

- Input archive: `cost_aware_momentum-1.8.20-acceptance-external-state-integrity.zip`
- Input SHA-256: `2f00d490a2843fdb8bd1c22af385ac989ba9cc6e88f7693f2680bed80032a208`
- Input version: `1.8.20`
- Output version: `1.8.21`
- Python: `3.13.5`
- Existing Alembic head: `0007_position_account_scope`
- Source Python files under `app/` and `scripts/`: 68
- Test Python files before this iteration: 38; after: 39
- Existing documentation files before the new report: 28
- No `.env`, virtual environment, cache, bytecode or model artifact was intentionally added to the release.

## 2. Goal and acceptance criteria

After this iteration, delivery-settled contracts returned by Bybit's broad `linear` category must not abort the USDT perpetual instrument synchronization, while malformed in-scope perpetual specifications must remain fail-closed.

Acceptance criteria:

1. `LinearFutures` is excluded before funding/spec validation.
2. A future with `fundingInterval=0` does not raise and is not persisted.
3. A valid `LinearPerpetual` in the same response is persisted normally.
4. Missing/zero/invalid funding interval on `LinearPerpetual` remains an error.
5. No order API, migration, environment variable or public API schema is introduced.
6. Relevant market-data and universe tests pass.

## 3. Sources and data flow

Read/reviewed:

- operator traceback dated 2026-07-01;
- `README.md`, `CHANGELOG.md`, `PATCH_1.8.20.md`;
- `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/SECURITY.md`, `docs/OPERATOR_MANUAL.md`;
- `app/bybit/client.py`;
- `app/services/market_data.py`;
- `app/services/universe.py`;
- existing instrument and universe tests;
- official Bybit V5 “Get Instruments Info” and “Enums Definitions” documentation checked 2026-07-01.

Affected flow:

```text
Bybit GET /v5/market/instruments-info?category=linear
→ BybitClient.get_instruments()
→ sync_instruments()
→ product-type filter
→ strict perpetual spec validation
→ Instrument / InstrumentSpecHistory
→ dynamic perpetual universe
```

The official API contract states that `category=linear` includes USDT perpetuals, USDT futures and USDC contracts. `contractType` distinguishes `LinearPerpetual` from `LinearFutures`. The endpoint documents `fundingInterval` in minutes, but a delivery future has no periodic perpetual funding obligation and may expose zero.

## 4. Baseline before changes

Commands and observed results:

- `python --version` — PASSED, Python 3.13.5.
- `python -m pip check` — FAILED because the shared environment has `moviepy 2.2.1` requiring `Pillow < 12` while `Pillow 12.2.0` is installed; unrelated to this project.
- `python -m compileall -q app scripts tests manage.py` — PASSED.
- `python -m ruff check .` — UNAVAILABLE, Ruff is not installed.
- `node --check web/js/app.js` — PASSED.
- `python -m pytest -q` — collection did not complete: 19 modules required missing package `psycopg`.
- PostgreSQL integration and `manage.py doctor` — NOT RUN; no safe test database, project `.venv` or application `.env`.

External runtime evidence:

- Bybit returned HTTP 200 for `/v5/market/instruments-info?category=linear&limit=1000`.
- `sync_instruments()` then raised `ValueError: Bybit field fundingInterval must be a positive integer` repeatedly.
- The worker retried and failed the initial synchronization and subsequent loop iterations.

## 5. Confirmed defect

### CONFIRMED DEFECT — high operational severity

- File: `app/services/market_data.py`
- Functions: `sync_instruments()`, `_instrument_spec_values()`
- Trigger: a USDT-settled `LinearFutures` row with `fundingInterval=0` in a successful `category=linear` response.
- Expected: the advisory system, explicitly scoped to USDT perpetuals, excludes the dated future and continues with perpetual rows.
- Actual in 1.8.20: the row reached `_instrument_spec_values()` before product-type exclusion and raised, aborting the full transaction/job.
- Impact: perpetual instrument/spec refresh stopped; worker entered repeated failure; market-data state could become stale and recommendations unavailable.
- Why previous tests missed it: fixtures contained only `LinearPerpetual` and assumed the transport category was already product-specific.

This is not evidence that Bybit returned malformed perpetual data. It is a local product-boundary error caused by treating the broad `linear` category as perpetual-only.

## 6. Plan and actual diff

Production:

- `app/services/market_data.py`: require `contractType == "LinearPerpetual"` immediately after USDT settlement filtering and before symbol/spec parsing.

Tests:

- `tests/unit/test_linear_perpetual_catalogue.py`: mixed-response regression with a dated future (`fundingInterval=0`) and a valid perpetual; verifies count and inserted symbol.

Version/release/docs:

- `app/__init__.py`, `pyproject.toml`;
- `README.md`, `CHANGELOG.md`, `PATCH_1.8.21.md`;
- `docs/ARCHITECTURE.md`, `docs/OPERATOR_MANUAL.md`, `docs/SECURITY.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this report and regenerated `SHA256SUMS`.

No migration, configuration or API change was needed.

## 7. Red → green evidence

Red command on unchanged production code with the new regression:

```text
python -m pytest -q tests/unit/test_linear_perpetual_catalogue.py
```

Result:

```text
1 failed
ValueError: Bybit field fundingInterval must be a positive integer
```

The exception arose on the `LinearFutures` fixture before the valid perpetual was processed, matching the operator traceback.

Green focused command after the production fix:

```text
python -m pytest -q \
  tests/unit/test_linear_perpetual_catalogue.py \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py \
  tests/unit/test_universe.py
```

Result: `12 passed`.

## 8. Compatibility

- Database migration: none.
- Alembic head: unchanged (`0007_position_account_scope`).
- `.env`: unchanged.
- Public API: unchanged.
- Stored in-scope perpetual schema: unchanged.
- Dated futures were already rejected later by `select_dynamic_universe()`; the change moves the same product boundary earlier so they no longer enter persistence/spec validation.
- Advisory-only and read-only Bybit boundaries remain unchanged.

## 9. Post-check

- Focused market-data/universe suite: PASSED — 12 tests.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `node --check web/js/app.js`: PASSED.
- Full pytest: NOT RUN to completion due missing `psycopg` in the supplied interpreter.
- Ruff: UNAVAILABLE.
- PostgreSQL integration: NOT RUN.
- Live Bybit smoke from sandbox: NOT RUN because outbound DNS/network is unavailable.
- Release integrity: PASSED — 163 eligible files and 163 manifest entries.
- ZIP validation: performed after packaging and recorded in the user-facing release response.

## 10. Unverified items

- exact symbol in the operator's mainnet response that carried zero funding was not captured in the supplied log;
- live response could not be downloaded from the sandbox;
- full test suite and PostgreSQL integration were not rerun in this environment;
- worker recovery against the user's existing PostgreSQL database was not observed directly.

## 11. Residual risks and limitations

- A malformed in-scope perpetual still intentionally aborts instrument synchronization; this is fail-closed but can cause broad availability loss until the exchange response or parser is corrected.
- Instrument-spec maximum-age enforcement remains a separate documented work package.
- The system has no historical orderbook impact model or proof of trading profitability.
- FastAPI's `ORJSONResponse` deprecation warning is unrelated and remains.

## 12. Rollback

1. Stop the worker (and API/trainer if they share the deployed source tree).
2. Restore version 1.8.20 source.
3. Restart processes.
4. No database downgrade or `.env` rollback is needed.

Rollback reintroduces the repeated worker failure when Bybit returns an out-of-scope future with zero funding interval.

## 13. Recommended next work package

Add point-in-time maximum-age/validity enforcement for `InstrumentSpecHistory`, with PostgreSQL integration coverage, so a repeatedly failing instrument refresh cannot leave an old specification usable indefinitely.
