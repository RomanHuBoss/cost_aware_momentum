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
| Point-in-time research dataset | `app/ml/training.py`, context/funding modules | point-in-time, tick geometry, funding replay tests |
| Frozen dynamic historical bootstrap | `app/workers/trainer.py::current_training_scope`, `app/ml/lifecycle.py::load_dynamic_bootstrap_cohort` | `tests/unit/test_historical_dynamic_bootstrap_2026_07_07.py` |
| Bootstrap preflight/artifact provenance | `require_training_universe_scope`, `evaluate_quality_gate` | bootstrap evidence/profile integrity tests |
| Exact prospective replay without full-sample symbol selection | `load_training_data_profile(require_universe_replay=True)` | `test_exact_dynamic_profile_never_applies_full_sample_symbol_cap` |
| Model lifecycle fail-closed | `app/ml/lifecycle.py`, promotion/activation services | lifecycle, activation, experiment governance tests |
| PostgreSQL migration head | `migrations/versions/0018_inference_observations.py` | Alembic head check; integration upgrade not run here |

Точное число и результат выполненных проверок фиксируются в `docs/QA_REPORT.md`; неподтверждённые external/live свойства не считаются закрытыми.
