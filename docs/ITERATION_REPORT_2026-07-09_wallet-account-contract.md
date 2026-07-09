# Iteration report — 2026-07-09 — wallet-account-contract

## 1. Input archive, SHA-256, source version

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `471f40e14cdaf858d2748197fbb5f5cf32f8afb840ecc664790f741e4cd04d9c`
- Source version: `1.52.16`
- New version: `1.52.17`
- Python requirement: `>=3.12`
- Runtime Python in sandbox: `Python 3.13.5`
- Alembic head: `0018_inference_observations (head)`
- Package/root: one extracted root directory, `cost_aware_momentum-main`

## 2. Goal and acceptance criteria

Goal: after this iteration, the read-only Bybit account path must fail closed before persisting account capital/equity snapshots when `/v5/account/wallet-balance` returns malformed or partial wallet payloads.

Acceptance criteria:

1. `BybitClient.get_wallet_balance()` rejects missing, null, or non-list `wallet-balance.result.list`.
2. `sync_read_only_account()` rejects wallet payloads without exactly one account row.
3. `sync_read_only_account()` rejects account rows without a `coin` JSON array before positions are fetched or DB writes are attempted.
4. `sync_read_only_account()` rejects account rows without a USDT coin row before positions are fetched or DB writes are attempted.
5. Existing valid read-only account fixtures still pass and continue stamping equity/position snapshots with the Bybit read-only account id.
6. No database migration, `.env` change, public API schema change, or order execution capability is introduced.
7. Version, changelog, patch note, QA report, compliance, traceability, and release manifest are updated.

## 3. Sources read and data flow map

Read context:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.13.md`, `PATCH_1.52.14.md`, `PATCH_1.52.15.md`, `PATCH_1.52.16.md`
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
- Relevant unit tests under `tests/unit/`

Project map used for this scope:

- Data ingestion / market data: `app/services/market_data.py`, `BybitClient` public endpoints.
- Account/profile logic: `sync_read_only_account()`, `AccountEquitySnapshot`, `PositionSnapshot`, `CapitalProfile`.
- Bybit client: `app/bybit/client.py` read-only GET methods only.
- Risk/execution plan dependency: capital/equity snapshots can influence execution plan sizing/status, while market signal remains independent of capital.
- ORM/outbox: account snapshot and outbox event are written by account sync after wallet and position validation.
- Tests: Bybit response contract tests plus account sync integrity tests.

## 4. Baseline

| Command | Status | Result |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | collection interrupted: `62 errors in 12.09s`; representative `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

PostgreSQL-free control subset before patch:

```text
74 passed in 6.04s
```

## 5. Confirmed defects/gaps

### Defect 1 — wallet balance client did not enforce `result.list`

- Type: CONFIRMED DEFECT
- Severity: high
- File/function: `app/bybit/client.py`, `BybitClient.get_wallet_balance()`
- Data path: Bybit `/v5/account/wallet-balance` → `_get(...).result` → `get_wallet_balance()` → `sync_read_only_account()`
- Factual behavior: malformed wallet balance results with missing/null/non-list `list` were returned downstream.
- Expected behavior: read-only account wallet payload must be list-shaped or fail closed.
- Impact: account capital/equity processing could continue from an ambiguous external payload, weakening fail-closed account sizing guarantees.
- Why existing tests missed it: the previous Bybit response contract test covered several list-shaped endpoints but not wallet balance.
- Reproduce: run the new malformed wallet-balance cases against version 1.52.16.
- Future guard: `tests/unit/test_bybit_response_contract_2026_07_09.py` includes wallet balance in missing/null/non-list list validation.

### Defect 2 — account sync treated missing wallet account list as empty/ambiguous state

- Type: CONFIRMED DEFECT
- Severity: high
- File/function: `app/services/market_data.py`, `sync_read_only_account()`
- Data path: `get_wallet_balance()` result → wallet account row selection → `totalEquity` / `totalAvailableBalance` → `AccountEquitySnapshot`
- Factual behavior: account sync used permissive wallet row extraction logic and did not own a strict wallet contract.
- Expected behavior: exactly one account row is required for the configured UNIFIED account snapshot.
- Impact: a malformed account payload could be conflated with a legitimate empty or partial account state.
- Why existing tests missed it: tests asserted malformed positions/equity paths, but not the wallet account structure itself.
- Reproduce: run account sync on a wallet response with an absent or malformed `list` in the original implementation.
- Future guard: `_validated_wallet_account()` is exercised by account sync regression tests.

### Defect 3 — account sync accepted account rows without a `coin` array

- Type: CONFIRMED DEFECT
- Severity: high
- File/function: `app/services/market_data.py`, `sync_read_only_account()`
- Data path: wallet account row → no `coin` array → equity snapshot persisted.
- Factual behavior: an account row with `totalEquity` and `totalAvailableBalance` but no `coin` array could be accepted.
- Expected behavior: the USDT-linear account path must require explicit coin-level evidence from the wallet payload.
- Impact: a partial wallet payload could verify and publish capital snapshots without the coin-level payload needed for USDT scope validation.
- Why existing tests missed it: existing wallet fixtures only checked top-level equity fields.
- Reproduce: `test_account_sync_rejects_wallet_without_coin_list_before_any_write` fails on 1.52.16 with `Failed: DID NOT RAISE <class 'RuntimeError'>`.
- Future guard: the new regression asserts no position fetch and no DB write after the invalid wallet payload.

### Defect 4 — account sync accepted account rows without USDT coin evidence

- Type: CONFIRMED DEFECT
- Severity: high
- File/function: `app/services/market_data.py`, `sync_read_only_account()`
- Data path: wallet account row → `coin` array with no `USDT` item → equity snapshot persisted.
- Factual behavior: an account row scoped to a non-USDT coin set could still feed the USDT-linear account snapshot.
- Expected behavior: advisory system scoped to Bybit linear USDT perpetuals must require a USDT coin row before using account capital.
- Impact: execution plan sizing/status could be derived from account evidence that is not explicitly tied to USDT account scope.
- Why existing tests missed it: fixtures used only top-level account equity and did not encode coin-scope validation.
- Reproduce: `test_account_sync_rejects_wallet_without_usdt_coin_before_any_write` fails on 1.52.16 with `Failed: DID NOT RAISE <class 'RuntimeError'>`.
- Future guard: the new regression asserts no position fetch and no DB write after the invalid wallet payload.

## 6. Actual diff by file

Production:

- `app/bybit/client.py`
  - `get_wallet_balance()` now calls `_require_result_list(result, "wallet balance")` before returning the result.
- `app/services/market_data.py`
  - Added `_validated_wallet_account()` to enforce wallet result dict, non-null list, list type, exactly one account row, dict row, `coin` list, and USDT coin-row presence.
  - `sync_read_only_account()` now uses `_validated_wallet_account(wallet)` before reading equity, fetching positions, or writing snapshots.
- `app/__init__.py`
  - Version bumped to `1.52.17`.

Tests:

- `tests/unit/test_bybit_response_contract_2026_07_09.py`
  - Wallet balance added to malformed list-shape contract coverage.
- `tests/unit/test_external_state_econometric_integrity_2026_06_30.py`
  - Added wallet `coin` array and USDT row regressions.
  - Updated valid wallet fixtures to include USDT coin evidence.
- `tests/unit/test_account_scope_integrity_2026_06_30.py`
  - Updated valid wallet fixture with USDT coin evidence.
- `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py`
  - Updated valid wallet fixture with USDT coin evidence.

Docs/release:

- `pyproject.toml`
- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.17.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/ITERATION_REPORT_2026-07-09_wallet-account-contract.md`
- `SHA256SUMS`

Migrations:

- None.

## 7. Red → green evidence

Red command, run against a clean extracted 1.52.16 tree after copying in the new regression tests:

```bash
python -m pytest -q \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_wallet_without_coin_list_before_any_write \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_wallet_without_usdt_coin_before_any_write
```

Red result:

```text
5 failed, 17 passed in 5.46s
```

Representative red line:

```text
Failed: DID NOT RAISE <class 'RuntimeError'>
```

Green command after implementation:

```bash
python -m pytest -q \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_malformed_open_position_before_any_write \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_missing_equity_before_persisting_snapshot \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_wallet_without_coin_list_before_any_write \
  tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_wallet_without_usdt_coin_before_any_write \
  tests/unit/test_account_scope_integrity_2026_06_30.py::test_account_sync_stamps_positions_with_same_account_id \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_account_snapshot_time_is_after_wallet_and_position_reads
```

Green result:

```text
26 passed in 5.15s
```

Broader PostgreSQL-free control command:

```bash
python -m pytest -q \
  tests/unit/test_risk_math.py \
  tests/unit/test_cost_aware_direction_selection.py \
  tests/unit/test_bybit_response_contract_2026_07_09.py \
  tests/unit/test_market_context_features_2026_07_05.py \
  tests/unit/test_point_in_time_funding_intervals_2026_07_05.py \
  tests/unit/test_labels_features.py \
  tests/unit/test_training_tick_geometry_alignment_2026_07_07.py
```

Result:

```text
77 passed in 6.21s
```

## 8. Migrations, API/config/env compatibility

- Migration: not required.
- Alembic head remains `0018_inference_observations (head)`.
- Public API schema: unchanged.
- Environment variables: unchanged.
- Advisory-only invariant: preserved. No order create/amend/cancel/withdraw methods or endpoints were added.

## 9. Post-check

| Command | Status | Result |
|---|---:|---|
| `python -m pip check` | FAILED | `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| targeted wallet/account pytest | PASSED | `26 passed in 5.15s` |
| PostgreSQL-free quant/client control subset | PASSED | `77 passed in 6.21s` |
| `python -m pytest -q` | FAILED | `62 errors in 12.06s`, representative `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| forbidden order/withdraw endpoint grep | PASSED | no forbidden endpoint strings found |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 282 files checked, 282 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 282 files checked, 282 manifest entries.` |

## 10. Not verified and residual risks

Not verified in this sandbox:

- Ruff static analysis: `ruff` is unavailable.
- Full pytest suite: collection still fails because `psycopg` is not installed.
- PostgreSQL integration tests and `manage.py doctor`: no safe configured PostgreSQL test database and missing `psycopg`.
- Live/paper/shadow Bybit connectivity.
- End-to-end model training, model activation, drift monitoring, and forward evidence.

Residual risks:

- Wallet/account timestamp freshness still relies on local receipt time; source/server-time alignment of account snapshots deserves a separate audit.
- This patch does not prove live edge, profitability, or model robustness.
- This patch does not resolve the environment dependency conflict or missing PostgreSQL driver.
- Empty-position semantics and multi-account wallet responses should be reviewed in a subsequent account snapshot work package.

## 11. Rollback procedure

1. Revert the files listed in section 6 to version `1.52.16`.
2. Restore `pyproject.toml` and `app/__init__.py` version to `1.52.16`.
3. Restore `SHA256SUMS` from the `1.52.16` archive or rerun `python scripts/release_integrity.py --write` after rollback.
4. Rerun targeted account/Bybit contract tests and the release integrity check.
5. No database downgrade is required because no migration was added.

## 12. Recommended next work package

Audit source-time/server-time/account freshness for read-only account snapshots: ensure wallet, position, equity, and profile updates are point-in-time aligned, have explicit stale diagnostics, and cannot verify capital from stale or mixed-time account evidence.
