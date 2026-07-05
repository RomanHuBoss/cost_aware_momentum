# Traceability

Состояние: release 1.26.2, 2026-07-05. Таблица связывает изменённый lifecycle-контракт с production-кодом, тестами и эксплуатационной документацией.

| ID | Требование / инвариант | Реализация | Проверка | Статус |
|---|---|---|---|---|
| ML-LC-01 | Fresh immutable candidate не перезаписывает active artifact | `app/ml/lifecycle.py::register_model_candidate` | existing lifecycle tests | Реализовано ранее |
| ML-LC-02 | Candidate без passed quality gate не активируется | `app/ml/lifecycle.py::require_passed_quality_gate`, `app/services/model_activation.py` | `test_model_activation_gate_enforcement_2026_07_05.py` | Проверено unit |
| ML-LC-03 | Normal activation требует `READY` preregistered evidence exact version/SHA-256/horizon | `app/services/model_promotion.py`, `app/services/model_activation.py` | `test_experiment_bound_model_promotion_2026_07_05.py` | Проверено unit |
| ML-LC-04 | Зарегистрированный inactive candidate повторно проверяется после появления evidence | `app/workers/trainer.py::reconcile_pending_activation` | `test_trainer_promotes_registered_candidate_after_evidence_becomes_ready` | Проверено red → green unit |
| ML-LC-05 | Non-READY evidence остаётся fail-closed | `app/workers/trainer.py::reconcile_pending_activation` | `test_deferred_promotion_remains_fail_closed_until_experiment_is_ready` | Проверено unit |
| ML-LC-06 | Activation защищена от смены incumbent и проверяет отсутствие/наличие ожидаемой active version | `app/services/model_activation.py::activate_registered_model` | existing atomic promotion tests; deferred call sets `enforce_expected_previous_version=True` | Проверено unit, PostgreSQL integration не выполнена |
| ML-LC-07 | Registry mutation, audit и outbox выполняются в одной транзакции | `app/services/model_activation.py::activate_registered_model` | existing activation/audit tests | Проверено unit |
| ML-LC-08 | После successful promotion trainer не запускает новый fit в том же cycle | `app/workers/trainer.py::run_scheduling_iteration` | `test_scheduling_iteration_does_not_retrain_after_deferred_activation` | Проверено red → green unit |
| CFG-01 | Operator может указать family после регистрации exact artifact | `.env.example`, `app/config.py`, `README.md` | static review, full test suite | Реализовано |
| OPS-01 | Пустая/неверная family не ослабляет gates | `reconcile_pending_activation`, `README.md`, `PATCH_1.26.2.md` | fail-closed unit test | Проверено unit |

## Непроверенная трассировка

- Реальная блокировка конкурентных PostgreSQL sessions и единственный active-row partial index не проверялись в этой среде из-за отсутствия отдельной test database.
- Экономический edge, частота рекомендаций и live profitability не следуют из lifecycle-тестов и требуют prospective data/evidence.
