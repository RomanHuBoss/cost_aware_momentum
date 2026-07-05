# Traceability

Состояние: release 1.26.3, 2026-07-05. Таблица связывает exact experiment-to-deployment policy contract с production-кодом, тестами и эксплуатационной документацией.

| ID | Требование / инвариант | Реализация | Проверка | Статус |
|---|---|---|---|---|
| ML-POL-01 | Candidate сохраняет immutable policy contract, использованный при quality evaluation | `app/ml/lifecycle.py::build_model_candidate`, `app/services/model_promotion.py::build_experiment_policy_binding` | full lifecycle suite; policy-binding unit tests | Проверено unit |
| ML-POL-02 | `READY` selected trial обязан совпасть с candidate policy по каждому deployment-relevant параметру | `app/services/model_promotion.py::evaluate_experiment_promotion_gate` | `test_promotion_rejects_ready_trial_using_nonproduction_costs_and_thresholds` | Проверено red → green unit |
| ML-POL-03 | Exact policy match допускает promotion при остальных passed evidence | `evaluate_experiment_promotion_gate` | `test_promotion_accepts_ready_trial_with_exact_production_policy_binding` | Проверено red → green unit |
| ML-POL-04 | Persisted passed gate инвалидируется после изменения production policy | `require_passed_experiment_promotion_gate`, `experiment_policy_binding_from_settings` | `test_activation_rejects_gate_after_deployment_policy_changes` | Проверено unit |
| ML-POL-05 | Legacy gate/candidate без policy binding не может пройти normal activation | `require_experiment_policy_binding`, trainer reconciliation, registry activation | `test_activation_rejects_legacy_gate_without_policy_binding`; deferred tests | Проверено unit |
| ML-POL-06 | Exact artifact binding version/SHA-256/horizon сохраняется вместе с policy binding | `app/services/model_promotion.py`, `app/ml/lifecycle.py` | `test_experiment_bound_model_promotion_2026_07_05.py` | Проверено unit |
| ML-POL-07 | Fresh, deferred и reviewed registry activation используют один contract | `scripts/train.py`, `app/workers/trainer.py`, `app/services/model_activation.py` | atomic/deferred/activation suites | Проверено unit |
| ML-POL-08 | Current deployment settings проверяются до state-changing activation | `register_and_activate_model_candidate`, `activate_registered_model` | policy mismatch and atomic promotion suites | Проверено unit |
| ML-LC-01 | Quality gate, artifact validation, active-version CAS, audit и outbox не ослаблены | existing lifecycle and activation services | `test_atomic_model_promotion.py`, `test_model_activation_gate_enforcement_2026_07_05.py` | Проверено unit |
| OPS-01 | Already active artifact не деактивируется автоматически; legacy inactive candidate требует retraining или explicit emergency rollback | `app/services/model_activation.py`, `README.md`, `PATCH_1.26.3.md` | static review and full suite | Реализовано |

## Непроверенная трассировка

- Реальная конкурентная блокировка нескольких PostgreSQL sessions и transaction rollback на отдельной test database не проверялись: `TEST_DATABASE_URL`/`POSTGRES_ADMIN_URL` отсутствовали.
- Exact historical point-in-time funding forecast policy не реализована; binding фиксирует нулевой дополнительный funding stress override и фактический historical realized funding evidence.
- Техническое совпадение experiment и production policy не доказывает live profitability, достаточную частоту рекомендаций или устойчивость edge.
