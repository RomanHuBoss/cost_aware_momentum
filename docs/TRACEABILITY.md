# Traceability

## Work package: intrahorizon mark-to-market and liquidation proxy

| Acceptance criterion | Production implementation | Tests |
|---|---|---|
| Hourly mark-price history is progressively backfilled with explicit type | `app/services/market_data.py::symbols_needing_history_backfill`, `sync_candle_history`; `app/workers/runner.py::history_backfill_job` | `test_progressive_history_backfill_persists_explicit_mark_price_type` |
| Label requires exact mark bars through modeled exit | `app/ml/training.py::make_barrier_dataset` | `test_barrier_dataset_attaches_exact_hourly_mark_path_and_liquidation`, `test_barrier_dataset_fails_closed_for_missing_mark_bar` |
| LONG/SHORT MTM signs are directionally correct | `app/ml/mtm.py::_directional_return`, `simulate_intrahorizon_margin_path` | LONG liquidation and SHORT excursion tests |
| Exit at bar open excludes later intrabar extremes | `simulate_intrahorizon_margin_path` | `test_exit_at_open_does_not_use_post_exit_intrabar_mark_extreme` |
| Actual adverse funding uses settlement timing in margin path | `make_barrier_dataset`, `simulate_intrahorizon_margin_path` | `test_adverse_funding_is_applied_before_conservative_intrabar_liquidation_check` |
| Invalid/nonfinite/misaligned path fails closed | same | `test_margin_path_rejects_nonfinite_or_misaligned_inputs` |
| Future mark path cannot affect ex-ante direction/EV | `app/ml/training.py::apply_intrahorizon_margin_path`, `evaluate_policy_model`; `scripts/backtest.py` | `test_future_mark_liquidation_cannot_change_ex_ante_direction_selection` |
| Runtime and gate require exact margin schema/assumptions | `app/ml/runtime.py`, `app/ml/lifecycle.py::evaluate_quality_gate` | artifact/runtime fixtures plus full suite |
| Candidate/incumbent comparison requires compatible leverage/reserve | `app/ml/lifecycle.py::build_model_candidate` | lifecycle compatibility regressions/full suite |

## Schema changes 1.13.0

- Intrahorizon margin: `bybit-mark-price-hourly-isolated-margin-proxy-v1`.
- Policy metrics: `decision-open-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v15`.
- Research source: exact confirmed hourly `price_type=mark`; future mark path is realized-only.

## Work package: historical funding settlement replay

| Acceptance criterion | Production implementation | Tests |
|---|---|---|
| Actual settlement timestamps are progressively backfilled | `app/services/market_data.py::sync_funding_history`, `app/workers/runner.py::history_backfill_job` | Bybit bounded-request regression plus static/full suite |
| Funding is aggregated only over `(entry_time, exit_time]` | `app/ml/funding.py::HistoricalFundingTimeline.aggregate` | `test_funding_replay_uses_open_closed_settlement_window` |
| Missing expected settlement fails closed | same | `test_funding_replay_fails_closed_on_missing_expected_settlement` |
| LONG pays and SHORT receives positive exchange funding | `app/ml/funding.py::funding_return_rate_for_direction` | `test_policy_funding_components_preserve_long_short_cashflow_signs` |
| Actual-exit funding affects realized PnL | `app/ml/training.py::evaluate_policy_model`, `scripts/backtest.py::policy_backtest` | funding component and policy selection tests |
| Future actual funding cannot affect ex-ante selection | same; `evaluate_quality_gate` contract | `test_future_funding_does_not_leak_into_policy_direction_selection`, gate regression |
| Artifact/runtime require settlement replay schema | `app/ml/lifecycle.py`, `app/ml/runtime.py` | runtime/artifact fixtures and full suite |
| Funding history query is bounded and read-only | `app/bybit/client.py::get_funding_history` | two Bybit request-contract tests |

## Schema changes 1.12.0

- Historical funding: `bybit-settlement-timestamp-replay-v1`.
- Policy metrics: `decision-open-directional-spread-entry-funding-timeline-exit-time-cohort-v14`.
- Expected funding source: `none-no-point-in-time-forecast`; realized source must equal the historical funding schema.

## Work package: purged expanding walk-forward validation

| Acceptance criterion | Production implementation | Tests |
|---|---|---|
| Final holdout исключён из development folds | `app/ml/lifecycle.py::evaluate_walk_forward_validation` | `test_walk_forward_validation_refits_models_before_final_holdout` |
| Три последовательных expanding folds | `app/ml/training.py::expanding_walk_forward_splits` | `test_expanding_walk_forward_is_purged_ordered_and_expanding` |
| Label overlap purged, horizon embargo соблюдён | same | same test |
| Каждый fold заново обучает и калибрует model | `evaluate_walk_forward_validation` | actual logistic refit test |
| Недостаточная история блокируется | splitter и `minimum_hourly_history_timestamps_for_quality_gate` | two minimum-history tests |
| Fold evidence сохраняется в candidate metrics/artifact | `build_model_candidate` | lifecycle/artifact fixtures and full suite |
| Runtime требует новую semantic schema | `app/ml/runtime.py::ModelRuntime.load` | incompatible training semantics parameterization |
| Gate блокирует временно нестабильный candidate | `app/ml/lifecycle.py::evaluate_quality_gate` | `test_quality_gate_rejects_walk_forward_temporal_instability` |
| Gate блокирует overlapping/tampered folds | same | `test_quality_gate_rejects_overlapping_walk_forward_test_windows` |

## Schema changes 1.11.0

- Temporal split: `final-holdout-plus-expanding-walk-forward-v4`.
- Walk-forward: `expanding-train-rolling-calibration-purged-v1`.

## Work package: execution-entry alignment

| Acceptance criterion | Production implementation | Tests |
|---|---|---|
| LONG entry adverse above next-hour open | `app/ml/training.py::make_barrier_dataset` | `test_training_labels_use_direction_specific_executable_entry_stress` |
| SHORT entry adverse below next-hour open | `app/ml/training.py::make_barrier_dataset` | same test |
| Invalid spread fails closed | `app/config.py`, `make_barrier_dataset` | `test_training_entry_spread_must_be_finite_and_nonnegative`, config test |
| Trainer and CLI pass configured spread | `app/workers/trainer.py`, `scripts/train.py` | Full suite/compile/static checks |
| Backtest uses artifact spread | `scripts/backtest.py` | Runtime/backtest contract covered by existing suite plus artifact tests |
| Artifact stores and validates execution metadata | `app/ml/lifecycle.py`, `app/ml/runtime.py` | runtime incompatible-semantics tests |
| Promotion gate rejects missing/mismatched metadata | `evaluate_quality_gate` | `test_quality_gate_rejects_missing_or_mismatched_entry_execution_model` |
| Incumbent comparison requires compatible entry geometry | `build_model_candidate` | incumbent geometry regression test |

## Schema changes

- Label path: `decision-open-directional-spread-entry-ohlc-path-v3`.
- Policy metrics: `decision-open-directional-spread-entry-exit-time-cohort-v13`.
- Entry execution: `directional-half-spread-on-next-hour-open-v1`.
