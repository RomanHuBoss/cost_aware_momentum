# Traceability

## Work package: point-in-time market-context features

| Acceptance criterion | Production implementation | Tests |
|---|---|---|
| Exact OI momentum 1h/24h without fill-forward | `app/ml/context.py::build_market_context_frame` | `test_context_features_use_only_exact_or_prior_market_events`, missing-history test |
| Exact mark/index basis and 1h change | same; index/mark candle backfill | same temporal feature test |
| Only latest already-settled funding enters features | `_attach_latest_settled_funding` | future-funding value regression |
| Missing/duplicate/non-finite context fails closed | context normalizers, dataset and live inference gates | missing and duplicate tests |
| Historical replay does not claim local receipt reconstruction | context metadata/artifact | metadata contract test |
| Live inference uses recorded availability cutoff | `app/services/signals.py::_market_context_values` | runtime contract/full suite |
| Index/OI history is progressively backfilled with bounded public requests | `app/services/market_data.py`, `app/workers/runner.py`, `BybitClient.get_open_interest` | bounded OI request test, full suite |
| Enriched model is compared with independently refit core comparator | `evaluate_market_context_ablation`, walk-forward validation | quality-gate ablation regression test |
| Runtime requires exact feature/context schemas | `app/ml/runtime.py` | missing context artifact contract test |
| Live refresh defaults are operationally enabled | `app/config.py`, `.env.example` | `test_market_context_live_refresh_is_enabled_by_default` |

## Schema changes 1.16.0

- Feature schema: `hourly-barrier-market-context-v4`.
- Context schema: `hourly-oi-basis-settled-funding-turnover-v1`.
- Availability schema: `exchange-event-close-live-receipt-v1`.
- Ablation schema: `same-split-zeroed-context-v1`.
- Alembic head unchanged: `0011_selection_experiment`.

## Work package: prospective operator-selection experiment ledger

| Acceptance criterion | Production/research implementation | Tests |
|---|---|---|
| Every plan version creates one experiment opportunity in the same transaction | `app/services/execution.py::create_execution_plan`, `SelectionExperimentLedger`, migration `0011` | `test_execution_plan_records_ex_ante_selection_experiment`, schema tests |
| Features are fixed before operator action and exclude outcome fields | `app/services/selection_experiments.py::_selection_feature_snapshot` | `test_selection_ledger_is_predecision_and_tamper_evident`, leakage test |
| Canonical SHA-256 detects modified ledger payload | `verify_selection_ledger_integrity` | tamper tests and report integrity test |
| ACCEPT, REJECT and absent decision are represented | `selection_bias_report` | `test_selection_report_counts_accept_reject_and_no_decision` |
| Propensity predictions are chronological out-of-sample | `app/research/selection_bias.py::_chronological_propensity_scores` | synthetic IPSW regression |
| Accepted-only bias is compared with observed all-eligible outcomes | `analyze_operator_selection` | `test_ipsw_reduces_selected_subset_bias_against_observed_eligible_benchmark` |
| Class collapse, poor overlap, low ESS and corruption do not emit a corrected estimate | same | class-collapse and integrity regressions |
| Operator report is explicit about non-causal interpretation | `scripts/selection_report.py`, `scripts/daily_report.py` | report contract tests/full suite |

## Schema changes 1.15.0

- Database head: `0011_selection_experiment`.
- Ledger schema: `selection-experiment-ledger-v1`.
- Feature schema: `operator-selection-predecision-v1`.
- Analysis schema: `operator-selection-ipsw-report-v1`.
- Evidence is prospective from 1.15.0; legacy plan opportunities are not backfilled.

## Work package: point-in-time orderbook execution evidence

| Acceptance criterion | Production implementation | Tests |
|---|---|---|
| Public read-only snapshot request is bounded | `app/bybit/client.py::get_orderbook` | `test_bybit_orderbook_request_clamps_supported_depth` |
| Exchange/source and receipt timestamps are preserved | `app/services/market_data.py::normalize_orderbook_snapshot` | normalization/future-time tests |
| Restart-safe natural identity and idempotent persistence | `app/db/models.py::OrderBookSnapshot`, migration `0010`, `sync_orderbooks` | natural-key and duplicate diagnostics tests |
| LONG consumes asks and SHORT consumes bids | `app/risk/liquidity.py::simulate_market_fill` | directional VWAP/impact tests |
| Partial/no-fill is explicit and complete fill is required | same; `app/services/execution.py::create_execution_plan` | partial-fill and depth-limited sizing tests |
| Size is capped by bounded depth and entry uses full-fill VWAP | `orderbook_depth_notional_cap`, iterative plan sizing | plan VWAP/cap regressions |
| Stale/future source or receipt time blocks execution | `orderbook_snapshot_is_fresh` | freshness test and acceptance suite |
| Acceptance revalidates entire qty and rejects legacy evidence | `app/api/v1/recommendations.py` | partial-depth, legacy-plan and adverse-entry tests |
| Decision audit stores exact fill and operator latency | operator decision `context_snapshot` | `test_acceptance_persists_exact_orderbook_fill_evidence` |
| Old snapshots are retained only for configured period | `app/workers/runner.py::retention_job` | static/full suite |

## Schema changes 1.14.0

- Database head: `0010_orderbook_exec_evidence`.
- Execution evidence: `bybit-rest-depth-vwap-fill-v1`.
- Model artifact schemas are unchanged from 1.13.0.
- Evidence is prospective only; no pre-1.14 historical reconstruction is claimed.

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
