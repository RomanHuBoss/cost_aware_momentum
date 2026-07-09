# Traceability

| Инвариант / требование | Production implementation | Regression / verification evidence |
|---|---|---|
| Release tree не может быть неполным | `scripts/release_integrity.py::_release_contract_errors` | `tests/unit/test_release_contract_2026_07_07.py` |
| Версия package/runtime/README совпадает | `scripts/release_integrity.py::_read_release_versions` | `test_release_verification_rejects_version_drift` |
| Forbidden artifacts и checksums | `inspect_release_tree`, `verify_release_tree`, `write_manifest` | `tests/unit/test_release_integrity.py` |
| Advisory-only | Bybit read-only client; отсутствие order mutation routes | static search + README/security contract |
| Directional and cost math | `app/risk/math.py` | `test_risk_math.py`, quant/econometric test modules |
| Capital-independent signal | `app/services/signals.py` | cost-aware direction and policy-alignment tests |
| Account-dependent plan/acceptance | `app/services/execution.py`, recommendation API | execution acceptance/manual risk tests |
| Acceptance не может обойти immutable decision-time entry zone | `app/api/v1/recommendations.py`, `app/services/execution.py::validate_execution_plan_for_acceptance` | `tests/unit/test_execution_acceptance_safety.py::test_acceptance_validator_rejects_current_entry_outside_signal_zone` |
| Quantity-safe orderbook sizing и aggregate VWAP acceptance | `orderbook_depth_notional_cap`, `validate_execution_plan_for_acceptance`, recommendation accept endpoint | `test_orderbook_vwap_sizing_integrity_2026_07_08.py`, multilevel acceptance regression |
| Point-in-time research dataset | `app/ml/training.py`, context/funding modules | point-in-time, tick geometry, funding replay tests |
| Frozen dynamic historical bootstrap | `app/workers/trainer.py::current_training_scope`, `app/ml/lifecycle.py::load_dynamic_bootstrap_cohort` | `tests/unit/test_historical_dynamic_bootstrap_2026_07_07.py` |
| Startup backfill reaches default training preflight depth | `app/config.py`, `app/services/market_data.py::sync_candles` | `tests/unit/test_initial_training_backfill_readiness_2026_07_08.py` |
| Bootstrap preflight/artifact provenance | `require_training_universe_scope`, `evaluate_quality_gate` | bootstrap evidence/profile integrity tests |
| Exact prospective replay without full-sample symbol selection | `load_training_data_profile(require_universe_replay=True)` | `test_exact_dynamic_profile_never_applies_full_sample_symbol_cap` |
| Model lifecycle fail-closed | `app/ml/lifecycle.py`, promotion/activation services | lifecycle, activation, experiment governance tests |
| Post-filter walk-forward shortage is deferred, not fatal | `WalkForwardCapacity`, `InsufficientWalkForwardHistoryError`, `BackgroundTrainer.run_training_once` | `test_fail_closed_incident_diagnostics_2026_07_08.py`, trainer recovery scheduling test |
| Decision-time contract warning preserves safe diagnostics | `app/logging.py::JsonFormatter`, `app/services/signals.py` | `test_json_formatter_preserves_safe_contract_diagnostics` |
| Signal-economics skips preserve exact fail-closed reason and context | `app/services/signals.py::classify_signal_economics_skip`, `app/logging.py::JsonFormatter` | `tests/unit/test_signal_economics_diagnostics_2026_07_08.py` |
| Stale hourly/catch-up decision publication is skipped before stale publish attempt | `app/workers/runner.py::resolve_decision_publication_window`, `Worker.hourly_decision_cycle`, `Worker.catchup_inference_job`, `Worker.inference_job` | `tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py` |
| Trainer effective wait reason falls back to persisted job failure | `app/api/v1/status.py::trainer_effective_wait_reason`, `web/js/app.js::trainerWaitDescription` | `tests/unit/test_trainer_status_diagnostics_2026_07_08.py`, `tests/unit/test_trainer_operator_ui.py` |
| Trainer explains rejected-candidate wait without hiding behind generic cooldown | `app/workers/trainer.py::_job_training_profile`, `app/workers/trainer.py::due_reason`, `web/js/app.js::trainerWaitDescription`, `web/js/app.js::trainerProgressRow` | `test_rejected_bootstrap_reports_new_data_wait_even_during_cooldown`, `test_rejected_bootstrap_recovers_profile_from_candidate_metrics`, `test_trainer_operator_ui.py` |
| NumPy dependency bound remains compatible with funding/policy contracts | `pyproject.toml` | full `pytest -q` under NumPy 2.3.5; NumPy 2.5.1 incompatibility documented in QA report |
| PostgreSQL migration head | `migrations/versions/0018_inference_observations.py` | Alembic head check; integration upgrade not run here |

Точное число и результат выполненных проверок фиксируются в `docs/QA_REPORT.md`; неподтверждённые external/live свойства не считаются закрытыми.

## 1.52.11 — Acceptance entry-zone validation boundary

- Requirement: immutable decision-time entry support must remain enforced at fresh acceptance, even if a stale plan still looks favorable by RR/EV.
  - Implementation: `validate_execution_plan_for_acceptance()` validates `signal.entry_low <= executable_price <= signal.entry_high` directly before risk/funding/RR checks.
  - Tests: `tests/unit/test_execution_acceptance_safety.py::test_acceptance_validator_rejects_current_entry_outside_signal_zone`.

## 1.52.7 — Open-interest backfill and stale hourly suppression

- Requirement: startup/progressive history must make the current training contract reachable without weakening temporal validation.
  - Implementation: `app/config.py` adds `history_backfill_open_interest_pages_per_symbol=7`; `app/workers/runner.py` uses it only for OI history; `/api/v1/status` exposes the value.
  - Tests: `tests/unit/test_initial_training_backfill_readiness_2026_07_08.py::test_default_open_interest_history_backfill_covers_training_quality_gate_precondition`.
- Requirement: stale recommendations must remain blocked without noisy repeated attempts in the same event hour.
  - Implementation: `Worker.hourly_decision_cycle_if_due` latches terminal stale hourly skips until the next event hour.
  - Tests: `tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py::test_repeated_stale_hourly_cycle_is_suppressed_until_next_event_hour`.

## 1.52.8 — Catch-up stale suppression and trainer failure diagnostics

- Requirement: stale catch-up publication must stay fail-closed without repeated terminal attempts for the same stale current-hour event.
  - Implementation: `Worker.catchup_inference_job` records `last_stale_catchup_inference_key=(reason, event_time)` after terminal `decision_publication_lag_exceeded` and returns `stale_catchup_inference_already_recorded` on duplicate attempts until the next event hour.
  - Tests: `tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py::test_repeated_stale_catchup_is_suppressed_until_next_event_hour`.
- Requirement: trainer UI must not say that no wait reason was reported when the latest persisted training job already contains a concrete failure.
  - Implementation: `/api/v1/status` derives `trainer_control.effective_wait_reason` from heartbeat `wait_reason` first, then from `last_result` / latest `model_retraining` job errors; UI consumes that field.
  - Tests: `tests/unit/test_trainer_status_diagnostics_2026_07_08.py`, `tests/unit/test_trainer_operator_ui.py`.

## 1.52.9 — Trainer wait progress clarity

- Requirement: a rejected/deferred candidate wait must be understandable to the operator as a safe data-dependent wait, not as a stuck trainer.
  - Implementation: `web/js/app.js` labels `quality_gate_failed_waiting_for_new_data` and `training_deferred_waiting_for_new_data` as normal protective waits, shows remaining new-labeled-hour threshold in `trainerProgressRow`, and adds a `Минимум до повтора` note.
  - Tests: `tests/unit/test_trainer_operator_ui.py::test_operator_ui_explains_labeled_hour_wait_as_progress_not_failure`.

## 1.52.10 — Signal economics skip diagnostics

- Requirement: fail-closed market-signal economics skips must be operator-diagnosable without weakening publication gates.
  - Implementation: `classify_signal_economics_skip()` maps stable economics validation failures to exact `reason_code` values; `record_symbol_outcome()` attaches safe context; `JsonFormatter` emits the fields.
  - Tests: `tests/unit/test_signal_economics_diagnostics_2026_07_08.py`.
