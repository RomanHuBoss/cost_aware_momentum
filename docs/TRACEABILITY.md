# Traceability

| Requirement / invariant | Production path | Verification |
|---|---|---|
| Post-response receipt timestamps | `app/services/market_data.py::sync_instruments`, `sync_tickers`, `sync_funding_and_oi`, `sync_read_only_account` | `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py` |
| Candle confirmation uses response time | `app/services/market_data.py::sync_candles`, `sync_candle_history`, `sync_candle_windows` | `test_candle_confirmation_uses_api_response_time` |
| Confirmed candle immutable without revision policy | `app/services/market_data.py::_upsert_candle_values` | `test_confirmed_candle_upsert_is_immutable_without_revision_policy` |
| Separate market and availability cutoffs | `app/services/signals.py::_candles_frame` | `test_feature_query_separates_market_and_availability_cutoffs` |
| Instrument spec available at decision time | `app/services/signals.py::_latest_spec`, `publish_hourly_signals` | `test_spec_query_uses_decision_availability_cutoff` |
| Post-fetch counterfactual cutoff | `app/workers/runner.py::counterfactual_outcome_job` | static flow review; PostgreSQL integration not run |
| Directional Decimal economics | risk/cost/execution services | full unit suite + independent 10 000-case audit |
| Barrier label parity | labels/outcomes/research paths | independent 5 000-case audit |
