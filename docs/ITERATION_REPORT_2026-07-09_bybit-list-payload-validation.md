# Iteration report — 2026-07-09 — bybit-list-payload-validation

## 1. Input archive, SHA-256, original version

- Input ZIP: `cost_aware_momentum-main.zip`
- Input ZIP SHA-256: `887acc0ff68a73465a28f6c072847460030a0d449fe44768361ca6c66c79ccdf`
- Prompt PDF: `Crypto Trading System Iteration Report.pdf`
- Prompt PDF SHA-256: `b743dae19bfa859715c5c924e54b45b002bd968eab7607e9e076643554ba55b9`
- Original project root: `cost_aware_momentum-main`
- Original version: `1.52.14`
- New version: `1.52.15`
- Version type: patch

## 2. Baseline and project boundary

### Detected project facts

- Package name: `cost-aware-momentum`
- Python requirement: `>=3.12`
- Observed Python in sandbox: `Python 3.13.5`
- Alembic head: `0018_inference_observations`
- Production file count before changes: 122
- Test file count before changes: 126
- Documentation/release file count before changes: 17
- Unexpected release artifacts in the original ZIP before baseline commands: none detected by the release-artifact scan. Later `compileall` generated local `__pycache__` files in the working tree; these were removed before release packaging.

### Preserved invariants

- Advisory-only: no order create/amend/cancel/withdraw capability was added.
- PostgreSQL-only: no SQLite fallback or schema change was added.
- Process split: no API/worker/trainer responsibilities were moved.
- Fail-closed behavior was strengthened for malformed exchange payloads.
- Market signal/execution plan separation was not changed.
- Model lifecycle, artifact gates, and activation logic were not changed.

## 3. Goal and acceptance criteria

Goal: after this iteration, read-only Bybit list endpoints must reject malformed non-list `result.list` payloads before downstream market-data, universe, or fee/account-cost logic can consume them.

Acceptance criteria:

1. `get_tickers()` rejects non-list `result.list` with an operator/developer-visible exception.
2. `get_kline()` rejects non-list `result.list` with an operator/developer-visible exception.
3. `get_fee_rate()` rejects non-list `result.list` with an operator/developer-visible exception.
4. The new regression test fails on the original implementation for the correct reason.
5. The new regression test passes after the minimal implementation fix.
6. Existing Bybit signature/no-order and open-interest client tests still pass in the targeted related check.
7. No migration, `.env`, public API schema, or endpoint-set change is introduced.

## 4. Sources read and project map

Read before selecting scope:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.14.md`
- `PATCH_1.52.13.md`
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
- Relevant production module: `app/bybit/client.py`
- Relevant tests: `tests/unit/test_execution_exchange_integrity_2026_07_01.py`, `tests/unit/test_market_context_features_2026_07_05.py`, `tests/unit/test_runtime_auth_config.py`

Project/data-flow map observed from docs and code:

- Data ingestion and market data: `app/bybit/client.py`, `app/services/market_data.py`, worker refresh paths.
- Instrument specs and exchange constraints: Bybit instruments/tickers/orderbook endpoints, `app/services/universe.py`, `app/risk/math.py`.
- Features and labels: `app/ml/features.py`, `app/ml/context.py`, `app/ml/labels.py`.
- Training, validation, artifact lifecycle: `app/ml/lifecycle.py`, `app/ml/training.py`, `app/ml/runtime.py`, model registry and activation services.
- Inference and market signal: worker runner plus `app/services/signals.py` and runtime predictions.
- Execution plan and risk/cost engine: `app/risk/math.py`, `app/risk/liquidity.py`, recommendation API plan paths.
- Account/profile logic: `app/api/v1/capital.py`, `app/services/market_data.py` account snapshot sync, risk caps.
- Bybit integration: `app/bybit/client.py`; read-only/public GET methods only.
- API schemas/frontend: `app/api/schemas.py`, `app/api/v1/*`, `web/js/app.js`.
- ORM/migrations: `app/db/models.py`, `migrations/versions/*`, Alembic head `0018_inference_observations`.
- Audit/idempotency/outbox: `app/services/audit.py`, `app/services/idempotency.py`, related DB-backed services.
- Tests: `tests/unit/*`, `tests/integration_postgres/*`.

## 5. Baseline commands and results

| Command | Status | Result |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | collection interrupted: `62 errors in 9.35s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 278 files checked, 278 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 278 files checked, 278 manifest entries.` |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

Baseline was not green.

## 6. Confirmed defect

### Malformed Bybit list payloads could pass through as valid endpoint output

- Type: CONFIRMED DEFECT
- Severity: high
- File: `app/bybit/client.py`
- Functions: `BybitClient.get_tickers()`, `BybitClient.get_kline()`, `BybitClient.get_fee_rate()`
- Path of data: Bybit HTTP response -> `_get()` retCode check -> endpoint method -> market-data/universe/candle/account-cost consumers.
- Actual behavior: when `retCode == 0` but `result.list` was a dict/string/scalar, the endpoint method returned that object directly.
- Expected behavior: list endpoints must validate that `result.list` is a JSON array and fail closed on malformed successful responses.
- Impact: malformed/stale/partial exchange responses could masquerade as valid market-data or fee-rate lists. This can corrupt ticker refresh, candle ingestion, universe selection, or fee assumptions, depending on downstream path and response shape.
- Why existing tests missed it: existing tests covered pagination loops, signature generation, no-order methods, and some list validation paths, but not tickers/kline/fee-rate non-list payload shape.
- Reproduction: monkeypatch `_get()` to return `BybitResponse(result={"list": {"not": "a-list"}}, ...)` and call `get_tickers()`, `get_kline()`, or `get_fee_rate()`.
- Future regression: `tests/unit/test_bybit_response_contract_2026_07_09.py::test_bybit_list_endpoints_reject_non_list_payloads`.

## 7. Red -> green evidence

### Red

Command:

```bash
python -m pytest -q tests/unit/test_bybit_response_contract_2026_07_09.py
```

Essential red result:

```text
FFF [100%]
Failed: DID NOT RAISE <class 'RuntimeError'>
Failed: DID NOT RAISE <class 'RuntimeError'>
Failed: DID NOT RAISE <class 'RuntimeError'>
3 failed in 0.55s
```

### Green

Command:

```bash
python -m pytest -q tests/unit/test_bybit_response_contract_2026_07_09.py
```

Essential green result:

```text
... [100%]
3 passed in 0.41s
```

Related Bybit/client contract command:

```bash
python -m pytest -q \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_execution_exchange_integrity_2026_07_01.py \
  tests/unit/test_market_context_features_2026_07_05.py::test_open_interest_client_supports_bounded_historical_queries
```

Essential result:

```text
........ [100%]
8 passed in 2.79s
```

## 8. Implementation and diff by file

Production:

- `app/bybit/client.py`
  - Added `_require_result_list(result, context)`.
  - Routed `get_tickers()`, `get_kline()`, and `get_fee_rate()` through the shared fail-closed list validator.
  - Removed the previous direct `result.get("list") or []` pass-through in those methods.

Tests:

- `tests/unit/test_bybit_response_contract_2026_07_09.py`
  - Added async parametrized regression for tickers, kline, and fee-rate non-list payloads.

Docs/release metadata:

- `pyproject.toml`: version `1.52.15`.
- `app/__init__.py`: version `1.52.15`.
- `README.md`: release banner updated.
- `CHANGELOG.md`: 1.52.15 entry added.
- `PATCH_1.52.15.md`: release patch note added.
- `docs/QA_REPORT.md`: baseline/red/green/post-check updated.
- `docs/SPEC_COMPLIANCE.md`: Bybit list-payload validation evidence added.
- `docs/TRACEABILITY.md`: new requirement/evidence row added.
- `docs/ITERATION_REPORT_2026-07-09_bybit-list-payload-validation.md`: this report added.

## 9. Migrations, API/config/env compatibility

- Alembic migration: not required.
- Alembic head observed: `0018_inference_observations`.
- `.env.example`: unchanged.
- Public API schemas: unchanged.
- Database schema: unchanged.
- Bybit endpoint set: unchanged.
- Advisory-only order/withdrawal surface: unchanged; forbidden endpoint grep in `app scripts web` found no order create/amend/cancel/withdraw endpoints.

## 10. Post-check commands and results

| Command | Status | Result |
|---|---:|---|
| `python -m pip check` | FAILED | same sandbox dependency conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q tests/unit/test_bybit_response_contract_2026_07_09.py` | PASSED | `3 passed in 0.41s` |
| related Bybit/client contract pytest | PASSED | `8 passed in 2.79s` |
| `python -m pytest -q` | FAILED | collection interrupted: `62 errors in 6.77s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| forbidden order/withdrawal endpoint grep in `app scripts web` | PASSED | no matches |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Post targeted counts: passed 8 / failed 0 / skipped 0 / xfailed 0 / errors 0.

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## 11. What could not be verified and why

- Ruff static analysis: `ruff` is not installed in the sandbox.
- Full pytest suite: collection imports PostgreSQL engine paths and `psycopg` is missing in the sandbox.
- PostgreSQL integration tests: no safe PostgreSQL test database was configured, and `psycopg` is missing.
- `manage.py doctor`: skipped for the same safe-PostgreSQL reason.
- Live/paper/shadow Bybit connectivity: not run; this iteration used mocked client responses only.
- End-to-end worker/API/trainer behavior: not run because database-backed flows are unavailable in this sandbox.

## 12. Residual risks and limitations

- This patch validates payload shape only at the endpoint-method boundary; it does not independently validate every field inside each ticker/kline/fee-rate row.
- Other private read-only account response structures may still need deeper semantic validation in downstream account snapshot parsing.
- Full-suite and PostgreSQL-backed regressions must be rerun in a configured development environment with `psycopg`, `ruff`, and a dedicated non-production PostgreSQL database.
- No profitability or live-edge claim is made.

## 13. Rollback procedure

1. Revert the version metadata from `1.52.15` to the previous release tag or deploy the previous `1.52.14` archive.
2. Revert `app/bybit/client.py` to the previous direct list extraction behavior only if the new fail-closed validation causes an unexpected compatibility issue with a verified valid Bybit response.
3. Remove `tests/unit/test_bybit_response_contract_2026_07_09.py` only as part of a full rollback; otherwise keep it as a regression guard.
4. No database rollback is required because no migration was added.
5. No `.env` rollback is required because no configuration variable changed.

## 14. Recommended next work package

Harden semantic validation of individual Bybit ticker/kline/fee-rate/account rows after list-shape validation: required fields, finite positive prices, non-negative volumes/turnover, timestamp monotonicity, and fail-closed diagnostics before market-data persistence or universe selection.
