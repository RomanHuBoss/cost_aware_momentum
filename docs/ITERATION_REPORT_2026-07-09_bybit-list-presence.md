# Iteration report — 2026-07-09 — bybit-list-presence

## Input archive, SHA-256, source version

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `1e7179230d77142f5ffad92a9ac68a9ef19d5a625a584ee17949b54a24273da0`
- Source version: `1.52.15`
- Output version: `1.52.16`
- Version type: patch
- Python observed in sandbox: `Python 3.13.5`
- Project root after unpack: `cost_aware_momentum-main`
- Alembic head: `0018_inference_observations (head)`
- Baseline source counts before generated caches: production Python files 98; test Python files 127; docs Markdown files 12; migration files 20; no `.env`, venv, pycache, pytest cache, build/dist, dumps, or model artifact files were present before checks.

## Goal and acceptance criteria

After this iteration the read-only Bybit client must fail closed when a list-shaped endpoint response is incomplete: `result.list` must be present, non-null, and a JSON array. A genuine empty exchange result remains valid only when Bybit explicitly returns `"list": []`.

Acceptance criteria:

1. Missing `result.list` is rejected for all list-shaped Bybit client methods.
2. `result.list == null` is rejected for all list-shaped Bybit client methods.
3. Existing non-list payload rejection remains intact.
4. Existing cursor pagination behavior for instruments and positions remains intact.
5. Funding history and open-interest bounded query behavior remains intact.
6. Advisory-only Bybit endpoint set remains unchanged; no order create/amend/cancel/withdraw endpoints are added.
7. No migration, `.env`, or public API schema change is introduced.
8. Documentation, version files, changelog, and traceability are synchronized.

## Sources read and data flow

Read sources:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.13.md`, `PATCH_1.52.14.md`, `PATCH_1.52.15.md`
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
- `tests/unit/test_bybit_response_contract_2026_07_09.py`
- relevant Bybit client tests for instruments, positions, funding history, and open interest.

Project map:

- Data ingestion / market data: `app/services/market_data.py`, `app/bybit/client.py`, worker modules.
- Features / labels / targets: `app/ml/features.py`, `app/ml/labels.py`, lifecycle/training modules.
- Training / validation / artifact lifecycle: `app/ml/lifecycle.py`, `app/ml/runtime.py`, trainer scripts/workers, model registry.
- Inference / market signal: worker and recommendation service modules under `app/services` and `app/api/v1`.
- Execution plan / risk / cost engine: `app/risk/math.py`, `app/risk/liquidity.py`, execution services.
- Account/profile logic: account, portfolio, recommendation and exposure modules.
- Bybit client: `app/bybit/client.py`, read-only V5 GET methods.
- API schemas/frontend: FastAPI under `app/api`, JS UI under `web/js/app.js`.
- ORM/migrations/audit/outbox: `app/db`, `app/models`, `migrations/versions`.
- Tests: `tests/unit`, `tests/integration_postgres`.

Relevant data path for this patch:

Bybit HTTP response → `BybitClient._get()` verifies `retCode == 0` → endpoint method extracts `result.list` → downstream market-data/account-cost/universe logic consumes the returned list. The defect was in the extraction step: missing or null `list` was converted to `[]`.

## Baseline results

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | collection interrupted: `62 errors in 8.47s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 280 files checked, 280 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 280 files checked, 280 manifest entries.` |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Confirmed defect

### Missing/null Bybit `result.list` accepted as valid empty list

- Type: CONFIRMED DEFECT
- Severity: high
- File: `app/bybit/client.py`
- Functions/classes/endpoints: `_require_result_list()`, `BybitClient.get_tickers()`, `get_kline()`, `get_fee_rate()`, `get_instruments()`, `get_funding_history()`, `get_open_interest()`, `get_positions()`.
- Data path: Bybit V5 JSON payload with `retCode == 0` → `BybitResponse.result` → endpoint list extraction → downstream market-data/account-cost/position/open-interest logic.
- Actual behavior: `result.get("list") or []` silently converted missing or null `result.list` to `[]`.
- Expected behavior: mandatory list-shaped endpoint responses must fail closed unless `result.list` is present and is a JSON array.
- Financial/model/operational/security impact: a stale, partial, or schema-broken exchange response could look like a legitimate empty list, causing false no-data/no-position/no-funding/no-instrument state instead of operator-visible failure diagnostics.
- Why existing tests missed it: existing regression only checked non-list values such as dicts, not absent or null list fields; paginated methods had separate non-list tests but also used the same fail-open `or []` pattern.
- Reproduction: monkeypatch `_get()` to return `BybitResponse(result={}, ...)` or `BybitResponse(result={"list": None}, ...)` and call any affected list-shaped method.
- Future test: `test_bybit_list_endpoints_reject_missing_or_null_list_payloads`.

## Plan and actual diff by file

Production:

- `app/bybit/client.py`
  - `_require_result_list()` now validates that result is a dict, `list` exists, `list` is not null, and the value is a list.
  - `get_instruments()`, `get_funding_history()`, `get_open_interest()`, and `get_positions()` now use `_require_result_list()`.
  - Removed a duplicate `seen_cursors.add(next_cursor)` line in `get_positions()` while touching the same pagination block; behavior is unchanged.

Tests:

- `tests/unit/test_bybit_response_contract_2026_07_09.py`
  - Added parametrized async regression for missing and null `list` payloads across tickers, kline, fee-rate, instruments, funding history, open interest, and positions.

Docs/release evidence:

- `pyproject.toml`
- `app/__init__.py`
- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.16.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/ITERATION_REPORT_2026-07-09_bybit-list-presence.md`
- `SHA256SUMS`

Migrations: none.

## Red → green evidence

Red command:

```bash
python -m pytest -q tests/unit/test_bybit_response_contract_2026_07_09.py
```

Red result on unpatched code after adding the regression:

```text
...FFFFFFFFFFFFFF [100%]
14 failed, 3 passed in 0.70s
```

Representative red line:

```text
Failed: DID NOT RAISE <class 'RuntimeError'>
```

Green command:

```bash
python -m pytest -q tests/unit/test_bybit_response_contract_2026_07_09.py
```

Green result after patch:

```text
................. [100%]
17 passed in 0.54s
```

Related regression command:

```bash
python -m pytest -q \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_get_instruments_follows_all_bybit_cursor_pages \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_get_instruments_rejects_repeated_cursor_instead_of_looping \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_get_instruments_rejects_non_list_page \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_get_positions_follows_all_bybit_cursor_pages \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_get_positions_rejects_repeated_cursor_instead_of_looping \
  tests/unit/test_historical_funding_replay_2026_07_05.py::test_bybit_funding_history_uses_bounded_end_time_pagination \
  tests/unit/test_historical_funding_replay_2026_07_05.py::test_bybit_funding_history_rejects_start_without_end \
  tests/unit/test_market_context_features_2026_07_05.py::test_open_interest_client_supports_bounded_historical_queries
```

Related result:

```text
......................... [100%]
25 passed in 2.78s
```

## Migration, API, config, env compatibility

- Alembic migration: not required.
- Alembic head unchanged: `0018_inference_observations (head)`.
- Public API schema: unchanged.
- `.env.example`: unchanged; no new variables.
- Bybit endpoint set: unchanged; no order create/amend/cancel/withdraw endpoints added.
- Advisory-only invariant: preserved.

## Post-check results

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | FAILED | same environment conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q tests/unit/test_bybit_response_contract_2026_07_09.py` | PASSED | `17 passed in 0.54s` |
| related Bybit/client contract pytest | PASSED | `25 passed in 2.78s` |
| `python -m pytest -q` | FAILED | collection interrupted: `62 errors in 7.48s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| order create/amend/cancel/withdraw endpoint grep in `app scripts web` | PASSED | no forbidden endpoint strings found |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 280 files checked, 280 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 280 files checked, 280 manifest entries.` |

Post targeted counts: passed 25 / failed 0 / skipped 0 / xfailed 0 / errors 0.

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Not verified and why

- Ruff static analysis: `ruff` is not installed in the sandbox.
- Full pytest suite: test collection imports PostgreSQL engine paths and `psycopg` is missing in the sandbox.
- PostgreSQL integration tests and `manage.py doctor`: no safe PostgreSQL test database was provided and `psycopg` is missing.
- Live/paper/shadow Bybit connectivity: not exercised in this offline archive iteration.
- End-to-end trainer, model activation, drift-monitoring, and production scheduler flows: not exercised because the environment lacks the required PostgreSQL setup.

## Residual risks and limitations

- This patch validates the presence/type of Bybit `result.list`; it does not independently validate every row schema inside those lists.
- Wallet-balance parsing outside the direct Bybit client list-return methods still deserves a separate focused audit.
- Full confidence in DB-backed flows requires a clean environment with project dev dependencies and an isolated PostgreSQL database.
- The patch is not evidence of live profitability or execution edge.

## Rollback procedure

1. Revert `app/bybit/client.py` and `tests/unit/test_bybit_response_contract_2026_07_09.py` to the previous release state.
2. Revert version files: `pyproject.toml`, `app/__init__.py`, `README.md`.
3. Remove `PATCH_1.52.16.md` and this iteration report.
4. Restore `CHANGELOG.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, and `SHA256SUMS` from the previous release.
5. Re-run targeted Bybit contract tests and release integrity before publishing the rollback archive.

## Recommended next work package

Audit wallet/account parsing and downstream account snapshot logic for the same class of fail-open behavior: missing `wallet.result.list`, missing `coin` arrays, stale account timestamps, and empty-position/account states should be distinguished from malformed or partial exchange responses.
