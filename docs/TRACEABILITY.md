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
| Quantity-safe orderbook sizing и aggregate VWAP acceptance | `orderbook_depth_notional_cap`, `validate_execution_plan_for_acceptance`, recommendation accept endpoint | `test_orderbook_vwap_sizing_integrity_2026_07_08.py`, multilevel acceptance regression |
| Point-in-time research dataset | `app/ml/training.py`, context/funding modules | point-in-time, tick geometry, funding replay tests |
| Frozen dynamic historical bootstrap | `app/workers/trainer.py::current_training_scope`, `app/ml/lifecycle.py::load_dynamic_bootstrap_cohort` | `tests/unit/test_historical_dynamic_bootstrap_2026_07_07.py` |
| Startup backfill reaches default training preflight depth | `app/config.py`, `app/services/market_data.py::sync_candles` | `tests/unit/test_initial_training_backfill_readiness_2026_07_08.py` |
| Bootstrap preflight/artifact provenance | `require_training_universe_scope`, `evaluate_quality_gate` | bootstrap evidence/profile integrity tests |
| Exact prospective replay without full-sample symbol selection | `load_training_data_profile(require_universe_replay=True)` | `test_exact_dynamic_profile_never_applies_full_sample_symbol_cap` |
| Model lifecycle fail-closed | `app/ml/lifecycle.py`, promotion/activation services | lifecycle, activation, experiment governance tests |
| Post-filter walk-forward shortage is deferred, not fatal | `WalkForwardCapacity`, `InsufficientWalkForwardHistoryError`, `BackgroundTrainer.run_training_once` | `test_fail_closed_incident_diagnostics_2026_07_08.py`, trainer recovery scheduling test |
| Decision-time contract warning preserves safe diagnostics | `app/logging.py::JsonFormatter`, `app/services/signals.py` | `test_json_formatter_preserves_safe_contract_diagnostics` |
| Stale hourly/catch-up decision publication is skipped before stale publish attempt | `app/workers/runner.py::resolve_decision_publication_window`, `Worker.hourly_decision_cycle`, `Worker.catchup_inference_job`, `Worker.inference_job` | `tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py` |
| Trainer explains rejected-candidate wait without hiding behind generic cooldown | `app/workers/trainer.py::_job_training_profile`, `app/workers/trainer.py::due_reason`, `web/js/app.js::trainerWaitDescription` | `test_rejected_bootstrap_reports_new_data_wait_even_during_cooldown`, `test_rejected_bootstrap_recovers_profile_from_candidate_metrics`, `test_trainer_operator_ui.py` |
| NumPy dependency bound remains compatible with funding/policy contracts | `pyproject.toml` | full `pytest -q` under NumPy 2.3.5; NumPy 2.5.1 incompatibility documented in QA report |
| PostgreSQL migration head | `migrations/versions/0018_inference_observations.py` | Alembic head check; integration upgrade not run here |

Точное число и результат выполненных проверок фиксируются в `docs/QA_REPORT.md`; неподтверждённые external/live свойства не считаются закрытыми.
