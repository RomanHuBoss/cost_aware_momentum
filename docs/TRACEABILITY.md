# Traceability

| Requirement / invariant | Evidence in 1.52.19 | Verification status |
|---|---|---|
| Advisory-only: no order create/amend/cancel/withdraw methods | `app/bybit/client.py`, `tests/unit/test_runtime_auth_config.py`; forbidden endpoint grep in `app scripts web` | Targeted grep passed after cache cleanup; full suite blocked by missing `psycopg` in sandbox |
| Bybit malformed/stale list payloads must not masquerade as valid lists, including missing or null `result.list` | `app/bybit/client.py::_require_result_list`, `tests/unit/test_bybit_response_contract_2026_07_09.py` | Existing targeted regressions retained; not fully rerun here |
| Ordinary last-trade Bybit kline rows must not persist impossible or incomplete OHLCV facts | `app/services/market_data.py::_validated_candle_ohlcv`, `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_still_reject_last_klines_missing_volume_turnover` | New regression passed |
| Bybit mark/index kline rows are price-only and must not be rejected for missing volume/turnover | `app/services/market_data.py::_validated_candle_ohlcv`, `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover` | New red→green regression passed |
| Malformed candle payloads must fail closed without candle upsert | `app/services/market_data.py::sync_candles`, `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_sync_candles_reports_malformed_ohlcv_without_persisting` | Included in related subset |
| Read-only wallet equity snapshots must not be created from partial Bybit wallet payloads | `app/services/market_data.py::_validated_wallet_account`, wallet/account regressions in `tests/unit/test_external_state_econometric_integrity_2026_06_30.py` | Existing coverage retained; not fully rerun here |
| PostgreSQL-only | `app/config.py`, `.env.example`, `tests/unit/test_runtime_auth_config.py` | Existing unit coverage; full suite blocked in this sandbox |
| Safe position sizing never rounds risk upward | `app/risk/math.py`, `tests/unit/test_risk_math.py` | Existing coverage retained; not rerun in this narrow iteration |
| Exchange cap is not min-order failure | `app/risk/math.py`, `tests/unit/test_risk_math.py::test_exchange_cap_block_is_not_reported_as_min_order` | Existing coverage retained; not rerun in this narrow iteration |
| Orderbook/liquidity evidence must not accept locked or crossed top-of-book states | `app/risk/liquidity.py::validate_orderbook_levels`, `tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book` | New red→green regression passed; related orderbook subset passed |
| Release evidence exists | `CHANGELOG.md`, `PATCH_1.52.19.md`, docs files, `SHA256SUMS` | Verified by `scripts/release_integrity.py --write` and `scripts/release_integrity.py` after cache cleanup |
