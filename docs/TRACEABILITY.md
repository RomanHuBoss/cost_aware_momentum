# Traceability

| Requirement / invariant | Evidence in 1.52.17 | Verification status |
|---|---|---|
| Advisory-only: no order create/amend/cancel/withdraw methods | `app/bybit/client.py`, `tests/unit/test_runtime_auth_config.py` | Existing unit coverage; full suite blocked by missing `psycopg` in sandbox |
| Bybit malformed/stale list payloads must not masquerade as valid lists, including missing or null `result.list` | `app/bybit/client.py::_require_result_list`, `tests/unit/test_bybit_response_contract_2026_07_09.py` | New targeted wallet regression passed |
| Read-only wallet equity snapshots must not be created from partial Bybit wallet payloads | `app/services/market_data.py::_validated_wallet_account`, `tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_wallet_without_coin_list_before_any_write`, `tests/unit/test_external_state_econometric_integrity_2026_06_30.py::test_account_sync_rejects_wallet_without_usdt_coin_before_any_write` | New targeted regressions passed |
| PostgreSQL-only | `app/config.py`, `.env.example`, `tests/unit/test_runtime_auth_config.py` | Existing unit coverage; full suite blocked by missing `psycopg` in sandbox |
| Safe position sizing never rounds risk upward | `app/risk/math.py`, `tests/unit/test_risk_math.py` | Existing targeted unit suite from previous release passed in prior evidence; full suite blocked in this sandbox |
| Exchange cap is not min-order failure | `app/risk/math.py`, `tests/unit/test_risk_math.py::test_exchange_cap_block_is_not_reported_as_min_order` | Existing regression; full suite blocked in this sandbox |
| Funding sign must not be invertible by negative position notional | `app/risk/math.py::funding_cash_flow`, `tests/unit/test_risk_math.py::test_funding_cash_flow_rejects_negative_position_value` | Existing regression from 1.52.14 |
| Fee cash must not allow negative/non-finite fee rates or invalid execution prices | `app/risk/math.py::fee_cash`, `tests/unit/test_risk_math.py::test_fee_cash_rejects_negative_fee_rate` | Existing regression from 1.52.14 |
| Release evidence exists | `CHANGELOG.md`, `PATCH_1.52.17.md`, docs files, `SHA256SUMS` | `scripts/release_integrity.py --write` and verify run after cache cleanup |
