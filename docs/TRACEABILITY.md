# Traceability

| Requirement / invariant | Evidence in 1.52.23 | Verification status |
|---|---|---|
| Advisory-only: no order create/amend/cancel/withdraw methods | `app/bybit/client.py`; forbidden endpoint grep in `app scripts web` | Passed; no exchange write endpoint implementation found |
| Locked/crossed ticker quotes must not become executable market evidence | `app/services/execution.py::validated_bid_ask`, `app/services/market_data.py::sync_tickers`, `app/services/universe.py::_spread_bps_from_prices` | Four new red→green regressions passed |
| Signal selection and acceptance must share the same strict quote geometry | `app/services/signals.py::select_cost_aware_scenario`, `app/services/execution.py::executable_entry_price` through `validated_bid_ask` | Targeted and related subsets passed |
| Dynamic universe must not classify a locked quote as zero-spread eligible | `app/services/universe.py::_spread_bps_from_prices`, `tests/unit/test_quote_plan_contract_2026_06_30.py::test_dynamic_universe_rejects_locked_quote` | Passed |
| Ticker ingestion may retain observational last price but must remove invalid executable bid/ask | `app/services/market_data.py::sync_tickers`, `tests/unit/test_quote_plan_contract_2026_06_30.py::test_ticker_sync_drops_locked_bid_ask` | Passed |
| Orderbook/liquidity evidence must reject locked or crossed top-of-book states | `app/risk/liquidity.py::validate_orderbook_levels`, `tests/unit/test_orderbook_execution_quality_2026_07_05.py` | Related subset passed |
| PostgreSQL-only | `app/config.py`, `.env.example`, unit suite | Full non-integration suite passed; PostgreSQL integration not run without a safe test DB |
| Safe position sizing never rounds risk upward | `app/risk/math.py`, risk unit suite | Full non-integration suite passed |
| Release evidence exists and archive hygiene is checked | `CHANGELOG.md`, `PATCH_1.52.23.md`, `docs/QA_REPORT.md`, `SHA256SUMS`, `scripts/release_integrity.py` | Verified during final release checks |
