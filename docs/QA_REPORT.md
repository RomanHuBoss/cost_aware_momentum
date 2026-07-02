# QA Report — 1.8.34

Дата: 2026-07-02

## Входной архив

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `5fb73ee5eb5014960d317539b507374e4776edc1203dfb09cd1c1c851b8cdf91`.
- Исходная версия: `1.8.33`; Python requirement: `>=3.12`.
- Alembic head: `0008_outcome_path_unavailable`.
- Входной архив не содержал заявленных `PATCH_*.md` и `SHA256SUMS`; эти release-артефакты восстановлены для 1.8.34.
- Утверждения о «20 critical + 7 medium + 18 critical» не содержали модулей, stack traces или воспроизводимых примеров. Они не считались подтверждёнными findings.

## Baseline до правок

Проверки выполнены в отдельном venv с установкой `-e .[dev]`.

| Проверка | Статус и результат |
|---|---|
| Python | PASSED — 3.13.5 |
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 416 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — one head `0008_outcome_path_unavailable` |
| `python manage.py doctor` | NOT RUN in comparable baseline — project-local `.venv`, `.env`, PostgreSQL tools/server unavailable |
| `python manage.py test --require-integration` | NOT RUN — no isolated `TEST_DATABASE_URL`/`POSTGRES_ADMIN_URL` |

## Подтверждённые defects

### 1. Повторное детерминированное обучение на неизменившихся данных — high

После `SUCCESS` job с `activation_skipped=quality_gate_failed` bootstrap/recovery использовал только шестичасовой cooldown. После его истечения кандидат повторно строился даже при идентичном `training_data_profile`. При фиксированном random state это воспроизводило тот же кандидат и те же причины gate failure, расходовало CPU и засоряло model/job history.

### 2. Перекрывающиеся часовые labels считались независимыми когортами — high

`policy_cohorts` равнялся числу raw decision timestamps. При horizon 8h решения в `t, t+1, …, t+7` используют перекрывающиеся future paths и не являются восемью независимыми временными наблюдениями. Promotion gate мог завышать объём эконометрического evidence.

### 3. Holdout rows не гарантировали календарную глубину — high

Большое число символов могло дать `AUTO_TRAIN_MIN_HOLDOUT_ROWS=180` на очень коротком final holdout. Gate не требовал минимального временного охвата и мог оценивать модель на одном узком режиме.

## Реализация

- Добавлен `policy_independent_cohorts`: greedy выбор decision timestamps с расстоянием не менее полного label horizon.
- `AUTO_TRAIN_MIN_POLICY_COHORTS` применяется к независимым, а не raw когортам.
- Добавлены `holdout_start_time`, `holdout_end_time`, `holdout_span_hours`, `holdout_unique_timestamps`.
- Добавлен fail-closed gate `AUTO_TRAIN_MIN_HOLDOUT_SPAN_HOURS=168`.
- После quality-gate rejection bootstrap ждёт `AUTO_TRAIN_MIN_NEW_TIMESTAMPS` или material profile change; explicit operator recovery не удалён.
- Policy metric schema повышена до `exit-time-open-gap-horizon-independent-cohort-v8`.
- Статус, `.env.example`, model card и operator documentation синхронизированы.

## Red → green

| Контракт | Red на 1.8.33 | Green на 1.8.34 |
|---|---|---|
| 20 соседних hourly cohorts при horizon 8h | отсутствовал `policy_independent_cohorts` | raw 20, independent 3 |
| 300 rows на holdout 47h | candidate проходил | `holdout_span_below_minimum` |
| rejected bootstrap после cooldown без новых данных | `due=True` | `quality_gate_failed_waiting_for_new_data` |
| rejected bootstrap после 168 новых timestamps | не различался с неизменившимся dataset | `due=True`, штатный retry |

## Post-check

| Проверка | Статус и результат |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py migrations` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 420 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — one head `0008_outcome_path_unavailable` |
| `python manage.py doctor` | FAILED ENVIRONMENT — `.env`, production secrets, `psql`/`pg_dump`/`pg_restore` и PostgreSQL server отсутствуют; Python/directories passed |
| `python manage.py test --require-integration` | NOT RUN — `TEST_DATABASE_URL`/`POSTGRES_ADMIN_URL` отсутствует |

## Compatibility и действия оператора

- Version: `1.8.34` (patch).
- Migration: none.
- Новая optional переменная: `AUTO_TRAIN_MIN_HOLDOUT_SPAN_HOURS=168`.
- Existing v7 promotion evidence должно быть пересчитано текущим trainer; действующая модель не деактивируется.
- Перезапустить API, inference worker и trainer.

## Остаточные риски

- Конкретные убыточные входы не воспроизведены: в архиве нет PostgreSQL state, candidate artifacts/metrics, signal/plan snapshots, fills и contemporaneous market data.
- Реальная PostgreSQL integration, migration smoke, backup/restore не выполнялись.
- Research по-прежнему не моделирует полный historical order book, no-fill/latency, точную funding timeline; full walk-forward, drift/regime governance и PBO/DSR остаются отдельным work package.
- Более строгий gate может временно уменьшить число активируемых моделей. Это ожидаемое fail-closed поведение, а не доказательство отсутствия стратегии.
- Зелёные тесты не доказывают экономическое преимущество или будущую прибыльность.
