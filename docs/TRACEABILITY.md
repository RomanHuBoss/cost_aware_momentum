# Traceability

Состояние: release 1.27.0, 2026-07-06. Таблица связывает critical production-drift publication interlock с production-кодом, тестами и release evidence.

| ID | Требование / инвариант | Реализация | Проверка | Статус |
|---|---|---|---|---|
| DRIFT-INT-01 | `CRITICAL` report должен latch exact active model version и переживать restart | `app/services/drift_monitor.py::production_drift_publication_guard`; persisted successful `JobRun` filtered by exact immutable model version | `test_current_model_critical_drift_latches_publication_quarantine` | Проверено red → green unit |
| DRIFT-INT-02 | Drift другой/предыдущей model version не должен блокировать новую active version | exact persisted report/model-version match in publication guard | `test_previous_model_critical_drift_does_not_quarantine_new_active_model` | Проверено unit |
| DRIFT-INT-03 | Runtime/signal version должна совпадать с current active registry | active registry consistency check before persisted drift lookup | `test_runtime_model_version_mismatch_fails_closed` | Проверено unit |
| DRIFT-INT-04 | Отключение новых monitor jobs не должно очищать persisted CRITICAL latch | guard enforcement не зависит от collection toggle | `test_disabling_monitor_does_not_clear_existing_critical_quarantine` | Проверено unit |
| DRIFT-INT-05 | Повторная activation того же immutable artifact не должна очищать его CRITICAL latch | historical exact-version critical evidence не ограничивается новым `updated_at` | `test_reactivating_same_artifact_version_does_not_clear_critical_latch` | Проверено unit |
| DRIFT-INT-06 | Critical drift должен проверяться до очередной hourly publication | `app/workers/runner.py::hourly_decision_cycle` | `test_hourly_cycle_evaluates_drift_before_inference` | Проверено unit |
| DRIFT-INT-07 | Под quarantine новые signals не должны обращаться к market/profile data и должны иметь объяснимую attrition | `app/services/signals.py::publish_hourly_signals` early short-circuit | `test_signal_publication_short_circuits_under_critical_drift` | Проверено unit |
| DRIFT-INT-08 | Новый/recalculated execution plan под quarantine не может быть actionable | `app/services/execution.py::create_execution_plan`; snapshot `production_drift_interlock` | `test_critical_drift_forces_execution_plan_to_no_trade` | Проверено unit |
| DRIFT-INT-09 | Ранее actionable plan нельзя принять после critical drift | `app/api/v1/recommendations.py::accept_recommendation`; conflict preserved before plan validation | `test_acceptance_rejects_actionable_plan_after_critical_drift` | Проверено red → green unit |
| DRIFT-INT-10 | Недостаток warm-up observations не должен создавать permanent bootstrap deadlock | guard latches only persisted `CRITICAL`, not diagnostic `BLOCKED` | guard tests + full suite | Проверено unit/analysis |
| COMPAT-01 | DB/API schema/env/model artifact/recommendation thresholds не изменены | migration отсутствует; existing contracts preserved | static diff, version/docs checks, full suite | Реализовано |
| BOUNDARY-01 | Advisory-only/read-only Bybit boundary не ослаблен | order mutation code не добавлен | static grep + full suite | Проверено static/unit |

## Непроверенная трассировка

- PostgreSQL persistence/concurrency integration не выполнялись: отдельная test DB и PostgreSQL tools отсутствуют.
- Не проверены multi-process timing races между activation и drift job на реальном PostgreSQL; exact-version predicates и existing transaction boundaries покрыты unit/static evidence.
- Forward/live прибыльность, достаточная частота рекомендаций и causal validity drift thresholds не доказаны.
- Interlock действует на всю active model version, а не selectively по symbol; automatic rollback и adaptive/multivariate drift control отсутствуют.
