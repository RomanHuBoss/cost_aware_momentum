# Traceability

Состояние: release 1.28.1, 2026-07-06. Таблица связывает critical drift evidence precedence с production-кодом, тестами и release evidence.

| ID | Требование / инвариант | Реализация | Проверка | Статус |
|---|---|---|---|---|
| DRIFT-STATUS-01 | Independently confirmed critical drift не должен подавляться blocker другой evidence dimension | `app/ml/drift.py::resolve_production_drift_status` и раздельные evidence lists | `test_confirmed_critical_feature_drift_dominates_incomplete_coverage` | Проверено red → green unit |
| DRIFT-STATUS-02 | Низкий coverage должен оставаться видимым blocker даже при overall `CRITICAL` | `blocking_evidence` + unchanged coverage section | тот же regression test | Проверено unit |
| DRIFT-STATUS-03 | Incomplete mature outcomes должны инвалидировать calibration-only evidence | `app/services/drift_monitor.py::build_production_drift_report` удаляет `calibration_drift`/`calibration_warning` перед final resolution | `test_incomplete_outcomes_without_independent_critical_evidence_remain_blocked` | Проверено unit |
| DRIFT-STATUS-04 | Incomplete mature outcomes не должны подавлять independent feature/probability/actionability critical evidence | blockers merge без overwrite critical list | `test_incomplete_outcomes_do_not_suppress_independent_critical_feature_drift` | Проверено red → green unit |
| DRIFT-STATUS-05 | Empty/sub-minimum warm-up не должен создавать ложный missingness critical | missingness critical требует configured minimum feature denominator | existing failed-inference/warm-up tests | Проверено unit |
| DRIFT-STATUS-06 | `CRITICAL` v3 report должен включать существующий exact-version quarantine action | final report status controls `automatic_model_action`; existing persisted guard remains status/version based | new service regression + `test_critical_drift_interlock_2026_07_06.py` | Проверено unit |
| DRIFT-STATUS-07 | Pure incomplete evidence остаётся `BLOCKED` и не создаёт bootstrap deadlock | status resolver selects BLOCKED only when critical list is empty | incomplete-only regression | Проверено unit |
| DRIFT-STATUS-08 | Report должен раскрывать причину каждого severity outcome | `critical_evidence`, `blocking_evidence`, `warning_evidence`, `alerts` | direct assertions in regression tests | Проверено unit |
| COMPAT-01 | DB/API/env/model artifact contracts не изменены | migration/config/API/artifact schemas untouched | static diff, full suite, version checks | Реализовано |
| BOUNDARY-01 | Advisory-only/read-only Bybit boundary не ослаблен | order mutation code не добавлен | static scan + full suite | Проверено static/unit |

## Непроверенная трассировка

- PostgreSQL integration tests не выполнялись: отдельная test database и project-managed runtime не настроены.
- Реальный persisted `JobRun` v3 → worker restart → quarantine cycle не проверен на PostgreSQL; unit tests проверяют report construction и persisted guard отдельно.
- Symbol/regime-conditional, multivariate и adaptive drift detection не реализованы.
- Исправление не доказывает прибыльность, не увеличивает частоту рекомендаций и не определяет причинность прошлых убытков.
