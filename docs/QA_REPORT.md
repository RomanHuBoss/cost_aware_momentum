# QA Report — 1.8.35

Дата: 2026-07-02

## Входной архив

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `a2b44aac0985a86bb3fdf45d53c1fc7813b26170873d80d4afe4b8565f1d7c89`.
- Исходная версия: `1.8.34`; Python requirement: `>=3.12`.
- Alembic head: `0008_outcome_path_unavailable`.
- Входной release не содержал заявленные `CHANGELOG.md`, `PATCH_*.md` и `SHA256SUMS`; это подтверждённый defect состава архива, восстановленный в 1.8.35.
- Утверждения о десятках ошибок не сопровождались файлами, stack traces или воспроизводимыми примерами и не использовались как доказательство. Findings ниже подтверждены кодом и regression tests.

## Baseline до правок

Основной baseline выполнен в чистом внешнем virtualenv с установкой `-e .[dev]`:

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **420 passed, 4 skipped, 19 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | one head: `0008_outcome_path_unavailable` |

System Python environment не считался проектным baseline: `pip check` обнаружил сторонний конфликт MoviePy/Pillow, Ruff отсутствовал, а pytest получил 23 collection errors из-за отсутствующего `psycopg`.

`python manage.py doctor` и `python manage.py test --require-integration` были вызваны, но завершились до проектных проверок, поскольку штатная локальная `.venv` не создавалась. Без отдельной безопасной PostgreSQL test database integration suite не запускалась; четыре integration tests корректно остались skipped в unit suite.

## Подтверждённые defects

### HIGH — trainer запускал математически непроходимый bootstrap

`app/workers/trainer.py::BackgroundTrainer.due_reason` использовал фиксированный минимум `300 + horizon + 72` (380 timestamps при horizon 8), не связанный с configured final-holdout gates. Фактический pipeline тратит 24 часа на feature warm-up, 8 часов на label horizon, применяет split 70/15/15 и horizon embargo. При 900 непрерывных часовых timestamps final holdout имеет только 122 часа вместо требуемых 168.

Следствие: candidate fit мог успешно завершиться, но затем неизбежно получать `holdout_span_below_minimum`; после rejection trainer переходил в cooldown/waiting-for-new-data. Это соответствует жалобе на «обученные за сутки модели не проходят границы запретов».

### HIGH — promotion не требовал skill относительно class-prior

`app/ml/training.py::evaluate_model` уже вычислял `class_prior_log_loss` и `log_loss_skill_vs_prior`, но `app/ml/lifecycle.py::evaluate_quality_gate` игнорировал эти метрики. Кандидат с отрицательным skill мог пройти абсолютный `AUTO_TRAIN_MAX_LOG_LOSS` и быть auto-activated при прохождении policy gates.

### MEDIUM — release provenance отсутствовала

Архив не содержал файлов, наличие которых утверждалось в QA/traceability: `CHANGELOG.md`, `PATCH_*.md`, `SHA256SUMS`. Код release checker присутствовал, но входной ZIP не мог пройти собственную provenance verification.

## Исправления

- Добавлен `minimum_hourly_history_timestamps_for_quality_gate()` — единый расчёт theoretical minimum raw hourly timestamps из feature warm-up, horizon, split, embargo, minimum holdout rows/span.
- При defaults trainer ждёт **1206** timestamps и возвращает диагностическую причину `not_enough_history_for_bootstrap` вместо запуска заведомо отклоняемого candidate.
- Gate требует конечный, строго положительный и внутренне согласованный `log_loss_skill_vs_prior`.
- Gate diagnostics теперь выводит class-prior log loss и skill.
- Active incumbent не деактивируется; risk/policy thresholds не ослаблялись.
- Версия, operator/model/security/compliance/traceability docs и release provenance синхронизированы.

## Red → green

До production fix два новых теста были запущены отдельно и оба упали по ожидаемой причине:

- `test_bootstrap_waits_until_configured_holdout_span_is_mathematically_possible`: фактически `due=True` при 900 timestamps.
- `test_quality_gate_rejects_model_without_skill_over_class_prior`: фактически `passed=True` при отрицательном skill.

После fix оба теста проходят. Полный post-check указан ниже.

## Post-check

| Проверка | Статус | Результат |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **422 passed, 4 skipped, 19 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | one head: `0008_outcome_path_unavailable` |
| release manifest/check | PASSED | 164 eligible files checked; 164 manifest entries |
| PostgreSQL integration | NOT RUN | безопасная отдельная test DB не предоставлена |
| `manage.py doctor` | NOT RUN TO COMPLETION | штатная local `.venv`/`.env`/PostgreSQL environment отсутствуют |

## Вывод

Техническая причина преждевременного обучения устранена; модель хуже class-prior больше не может пройти promotion. Это не доказательство доходности и не обещание большей частоты рекомендаций. Fee/slippage/EV/risk/data gates могут корректно приводить к `NO_TRADE`. Для вывода о фактических потерях нужны реальные candidate metrics, signal/plan snapshots и fills из рабочей PostgreSQL.
