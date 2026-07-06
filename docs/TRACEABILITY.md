# Traceability

Состояние: release 1.28.2, 2026-07-06. Таблица связывает point-in-time training-universe integrity с production-кодом, тестами и release evidence.

| ID | Требование / инвариант | Реализация | Проверка | Статус |
|---|---|---|---|---|
| TRAIN-UNIVERSE-01 | Historical training cohort не должен определяться ticker evidence позже label cutoff | `app/ml/lifecycle.py::_select_training_symbols` использует только confirmed `Candle` rows до `latest - horizon` | `test_dynamic_training_universe_uses_label_eligible_candle_history_not_latest_ticker` | Проверено red → green unit |
| TRAIN-UNIVERSE-02 | Dynamic cohort должен исключать symbols без configured minimum history | SQL `HAVING count(candle.id) >= minimum_rows_for_coverage` | тот же regression test проверяет SQL contract и threshold 300 | Проверено unit |
| TRAIN-UNIVERSE-03 | Stale historical symbol не должен считаться current label-eligible cohort member | SQL требует `max(open_time) >= label_cutoff` | тот же regression test проверяет cutoff reach contract | Проверено unit |
| TRAIN-UNIVERSE-04 | Selection должна быть детерминированной | ordering: row count DESC, latest eligible candle DESC, symbol ASC | SQL contract assertion + full suite | Проверено unit/static |
| TRAIN-UNIVERSE-05 | Empty dynamic cohort должен fail-closed, а не раскрывать unrestricted all-symbol query | `_select_training_symbols` различает explicit list и `None`; downstream filters use `is not None` | targeted regression + full lifecycle suite | Проверено unit |
| TRAIN-UNIVERSE-06 | Preflight profile и actual fit должны использовать один symbol cohort | `app/workers/trainer.py::run_training_once` передаёт exact `trigger.training_data_profile.symbols` как explicit scope | existing trainer/lifecycle suite + static flow inspection | Проверено unit/static |
| TRAIN-UNIVERSE-07 | Manual and background training должны использовать одинаковые horizon/min-history semantics | `scripts/train.py` и background trainer передают `horizon` и `minimum_rows_for_coverage` | full suite | Проверено unit |
| GATE-01 | Исправление не должно ослаблять quality/policy/promotion gates | thresholds/config untouched; 1206 timestamp bootstrap requirement unchanged | config diff + full suite | Реализовано |
| COMPAT-01 | DB/API/env/model artifact contracts не изменены | migration/config/API/artifact schemas untouched | Alembic head, static diff, full suite | Реализовано |
| BOUNDARY-01 | Advisory-only/read-only Bybit boundary не ослаблен | order mutation code не добавлен | static scan + full suite | Проверено static/unit |

## Непроверенная трассировка

- PostgreSQL integration tests не выполнялись: отсутствуют `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` и локальный PostgreSQL.
- Реальный query plan/performance на большой production candle table не измерен; запрос использует существующие candle filters/indexes, но требует PostgreSQL smoke/profiling.
- Историческая фактическая membership live dynamic universe, исторические spread/turnover eligibility и delisting state до начала локального хранения не реконструированы.
- Исправление не доказывает положительный edge, не увеличивает частоту рекомендаций и не устанавливает причинность прошлых убытков.
