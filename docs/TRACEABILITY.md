# Traceability

| Requirement / invariant | Evidence in 1.52.18 | Verification status |
|---|---|---|
| Advisory-only: no order create/amend/cancel/withdraw methods | `app/bybit/client.py`, `tests/unit/test_runtime_auth_config.py`; forbidden endpoint grep in `app scripts web` | Targeted grep passed; full suite blocked by missing `psycopg` in sandbox |
| Bybit malformed/stale list payloads must not masquerade as valid lists, including missing or null `result.list` | `app/bybit/client.py::_require_result_list`, `tests/unit/test_bybit_response_contract_2026_07_09.py` | Existing targeted Bybit regressions included in PostgreSQL-free subset |
| Bybit kline rows must not persist impossible market facts | `app/services/market_data.py::_validated_candle_ohlcv`, `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_invalid_ohlcv_rows_before_persistence` | New red→green regression passed |
| Malformed candle payloads must fail closed without candle upsert | `app/services/market_data.py::sync_candles`, `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_sync_candles_reports_malformed_ohlcv_without_persisting` | New targeted regression passed |
| Read-only wallet equity snapshots must not be created from partial Bybit wallet payloads | `app/services/market_data.py::_validated_wallet_account`, `tests/unit/test_external_state_econometric_integrity_2026_06_30.py` wallet/account regressions | Included in PostgreSQL-free subset |
| PostgreSQL-only | `app/config.py`, `.env.example`, `tests/unit/test_runtime_auth_config.py` | Existing unit coverage; full suite blocked in this sandbox |
| Safe position sizing never rounds risk upward | `app/risk/math.py`, `tests/unit/test_risk_math.py` | `tests/unit/test_risk_math.py` passed in targeted subset |
| Exchange cap is not min-order failure | `app/risk/math.py`, `tests/unit/test_risk_math.py::test_exchange_cap_block_is_not_reported_as_min_order` | Included in targeted subset |
| Funding sign must not be invertible by negative position notional | `app/risk/math.py::funding_cash_flow`, `tests/unit/test_risk_math.py::test_funding_cash_flow_rejects_negative_position_value` | Included in targeted subset |
| Fee cash must not allow negative/non-finite fee rates or invalid execution prices | `app/risk/math.py::fee_cash`, `tests/unit/test_risk_math.py::test_fee_cash_rejects_negative_fee_rate` | Included in targeted subset |
| Release evidence exists | `CHANGELOG.md`, `PATCH_1.52.18.md`, docs files, `SHA256SUMS` | Verified by `scripts/release_integrity.py --write` and `scripts/release_integrity.py` after cache cleanup |
