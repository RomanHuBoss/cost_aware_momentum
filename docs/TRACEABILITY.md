# Traceability

| Requirement / invariant | Production path | Verification |
|---|---|---|
| Post-response receipt timestamps | `app/services/market_data.py::sync_instruments`, `sync_tickers`, `sync_funding_and_oi`, `sync_read_only_account` | `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py` |
| Candle confirmation uses response time | `app/services/market_data.py::sync_candles`, `sync_candle_history`, `sync_candle_windows` | `test_candle_confirmation_uses_api_response_time` |
| Confirmed candle immutable without revision policy | `app/services/market_data.py::_upsert_candle_values` | `test_confirmed_candle_upsert_is_immutable_without_revision_policy` |
| Separate market and availability cutoffs | `app/services/signals.py::_candles_frame` | `test_feature_query_separates_market_and_availability_cutoffs` |
| Instrument spec available at decision time | `app/services/signals.py::_latest_spec`, `publish_hourly_signals` | `test_spec_query_uses_decision_availability_cutoff` |
| Current executable entry for account plan | `app/services/execution.py::create_execution_plan`, `executable_entry_price` | `test_execution_plan_reprices_from_current_executable_quote` |
| Missing bid/ask fails closed | `app/services/execution.py::create_execution_plan` | `test_execution_plan_fails_closed_when_executable_quote_is_missing` |
| Entry-zone enforced during plan creation/recalculation | `app/services/execution.py::create_execution_plan` | `test_execution_plan_marks_quote_outside_entry_zone_as_no_trade` |
| Terminal/blocking status precedence | `app/services/execution.py::create_execution_plan` | `test_terminal_signal_status_is_not_overwritten_by_liquidation_diagnostic` |
| Non-negative live minimum EV | `app/config.py::Settings.validate_cross_field_policy` | `test_negative_minimum_net_ev_is_rejected` |
| Economically non-losing auto-activation floors | `app/config.py::Settings.validate_cross_field_policy` | `test_auto_activation_rejects_economically_losing_absolute_gate` |
| Post-fetch counterfactual cutoff | `app/workers/runner.py::counterfactual_outcome_job` | static flow review; PostgreSQL integration not run |
| Directional Decimal economics | risk/cost/execution services | full unit suite; independent formulas covered by risk tests |
| Barrier label parity | labels/outcomes/research paths | unit parity tests |
| Manual/paper allocated capital is margin capacity | `app/services/execution.py::effective_capital` | `test_manual_profile_allocated_capital_is_theoretical_margin_capacity`, `test_manual_profile_margin_capacity_limits_position_sizing` |
| Actual entry fee replaces modeled entry fee | `app/risk/math.py::actual_fill_stress_loss`, `app/api/v1/trades.py::manual_entry` | `test_actual_fill_stress_loss_replaces_only_the_modeled_entry_fee`, fee-overrun endpoint test |
| Manual fill cannot consume unreserved risk or margin | `app/api/v1/trades.py::manual_entry` | stress-loss reservation and accepted-margin regression tests |
| Manual fee UI declares cash unit | `web/index.html` | `test_manual_entry_fee_label_declares_cash_unit` |
| Existing accepted/open margin reduces new capacity | `app/services/execution.py::reserved_margin_usdt`, `app/risk/math.py::calculate_position_plan`, acceptance validation | reservation aggregation, sizing-cap and acceptance rejection tests |
| Entry ticks cannot expand continuous policy band | `app/services/signals.py::select_cost_aware_scenario` | `test_entry_zone_rounding_never_expands_beyond_continuous_policy_band` |
| Private GET signature covers exact transmitted query | `app/bybit/client.py::BybitClient._get` | `test_private_get_signature_matches_exact_transmitted_query` |
| Known TradFi symbol types excluded from crypto domain | `app/services/universe.py::select_dynamic_universe` | default-exclusion and explicit-opt-in tests in `test_execution_exchange_integrity_2026_07_01.py` |
| Training/inference ATR barrier parity | `app/services/signals.py::publish_hourly_signals`, `app/ml/training.py::make_barrier_dataset` | `test_signal_policy_uses_the_exact_model_atr_without_hidden_clipping` |
| Artifact semantic schemas | `app/ml/runtime.py::ModelRuntime.load` | four cases in `test_runtime_rejects_artifacts_with_incompatible_training_semantics` |
| Comparable candidate/incumbent barrier geometry | `app/ml/lifecycle.py::build_model_candidate` | `test_incumbent_with_different_barrier_geometry_is_not_compared_on_candidate_labels` |
| No-loss profit-factor semantics | `app/ml/training.py::evaluate_policy_model`, `app/ml/lifecycle.py::evaluate_quality_gate` | `test_quality_gate_treats_positive_no_loss_profit_factor_as_unbounded` |
| Backtest artifact validation and hash | `scripts/backtest.py::load_validated_artifact` | `test_backtest_loader_enforces_runtime_artifact_contract` |
| Release provenance manifest | `scripts/release_integrity.py`, `SHA256SUMS` | release check on repacked tree |
| Plan outcome cannot reuse pre-plan price path | `app/services/outcomes.py::_record_plan_outcome`, migration `0008_plan_outcome_path_unavailable` | `test_late_execution_plan_does_not_reuse_pre_entry_signal_path`, schema test; PostgreSQL backfill not run |
| UI does not present unavailable-path zero as P&L | `web/js/app.js` | `test_frontend_marks_unavailable_path_without_numeric_pnl`, `node --check` |
| Profit factor gross legs do not net by exit timestamp | `app/ml/training.py::evaluate_policy_model` | `test_profit_factor_does_not_net_simultaneous_winner_and_loser` |
| Bounded funding-anchor advancement | `app/risk/math.py::projected_funding_rate` | `test_funding_projection_advances_stale_anchor_arithmetically` |
| Execution spec availability cutoff | `app/services/execution.py::latest_spec` | `test_execution_spec_query_respects_receipt_cutoff` |
