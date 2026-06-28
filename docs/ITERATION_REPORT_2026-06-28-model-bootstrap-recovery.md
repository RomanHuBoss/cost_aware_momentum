# Отчет об итерации 1.7.3 — immediate bootstrap/recovery training

Дата: 28 июня 2026 г.

Входной архив: `cost_aware_momentum-1.7.2-model-artifact-recovery.zip`

SHA-256 входного архива:

```text
3495386c9ed9f056641b1d6a39c2fff7aee7bc02e23b23d08a9ec93481b94852
```

Версия до изменения: `1.7.2`

Версия после изменения: `1.7.3`

## Цель итерации

После этой итерации система должна автоматически начать обучение полноценной ML-модели после startup delay, когда usable trained model отсутствует и worker работает на разрешенном deterministic baseline. Удаленный active artifact, отсутствие active registry row или active baseline не должны ждать обычного weekly/data-change trigger и не должны наследовать длинный cooldown от несвязанной старой ошибки.

Подтверждение: deterministic scheduler tests для фактического `BackgroundTrainer.due_reason()`, полный unit suite, Ruff, compileall и JavaScript syntax check.

## Границы изменения

Изменение ограничено scheduler-частью background trainer:

- определение bootstrap/recovery trigger;
- связывание cooldown с конкретным recovery episode;
- короткий backoff после технической ошибки recovery;
- конфигурация, tests и документация.

Не изменялись:

- advisory-only граница;
- Bybit client и order semantics;
- PostgreSQL schema и Alembic migrations;
- ML features, labels, fitting и quality-gate thresholds;
- atomic activation, registry integrity и audit/outbox;
- production fail-closed поведение;
- worker runtime fallback версии 1.7.2.

## Baseline до правок

Фактический корень архива определен как один каталог `cost_aware_momentum-1.7.2-model-artifact-recovery`.

Проверки исходной версии:

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5; проект требует Python >=3.12 |
| `python -m pip check` | FAILED (host environment) | внешний конфликт `moviepy 2.2.1` требует `pillow<12`, установлен `pillow 12.2.0`; проект эти пакеты не объявляет |
| `python -m compileall -q app scripts tests manage.py` | PASSED | без вывода |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 88 passed, 3 skipped |
| `node --check web/js/app.js` | PASSED | без вывода |
| `python manage.py doctor` | NOT RUN | пользовательский `.env`, native PostgreSQL service и credentials в среде сборки не настроены |
| `python manage.py test --require-integration` | NOT RUN | отдельная PostgreSQL test database отсутствует |

Три skipped test относятся к PostgreSQL integration. SQLite/fallback database не применялась.

## Подтвержденный дефект

Классификация: `CONFIRMED DEFECT`, severity `high` для операционного восстановления paper/shadow.

### Путь данных

```text
active registry row указывает на удаленный .joblib
→ worker 1.7.2 выбирает controlled deterministic baseline
→ trainer.due_reason() видит обычную trained registry row
→ scheduler проверяет dataset-change/new timestamps
→ либо возвращает not_enough_new_or_changed_training_data,
  либо применяет AUTO_TRAIN_RETRY_HOURS к последнему несвязанному FAILED job
→ полноценная модель не начинает обучаться после запуска
```

### Фактическое поведение до исправления

Для пользовательского состояния:

- active registry version существовала;
- artifact отсутствовал;
- worker работал на baseline;
- последний job имел `FAILED` и trigger `material_training_dataset_change`;
- `AUTO_TRAIN_RETRY_HOURS=6`.

Trainer не создавал самостоятельный recovery trigger. Он мог ожидать шесть часов либо требовать обычный прирост данных, хотя usable ML-модели не было.

### Ожидаемое поведение

После `AUTO_TRAIN_INITIAL_DELAY_SECONDS`, при достаточной истории и coverage:

1. отсутствующий artifact формирует `bootstrap_recovery`;
2. отсутствие active model или active deterministic baseline формирует `bootstrap_training`;
3. несвязанный предыдущий scheduled/data-change job не блокирует новый recovery episode;
4. повторная техническая ошибка того же episode использует короткий backoff;
5. quality-gate failure не активирует кандидата и не создает tight retraining loop.

## Red → green

До production implementation добавлен `tests/unit/test_trainer_recovery_scheduling.py`.

Команда RED:

```text
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py
```

Результат RED:

```text
4 failed
```

Существенные причины:

- missing artifact возвращал `not_enough_new_or_changed_training_data` вместо `bootstrap_recovery`;
- failed recovery не имел короткого backoff;
- unrelated failed scheduled job блокировал baseline bootstrap общим cooldown.

После исправления targeted command:

```text
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py
```

Результат GREEN:

```text
7 passed
```

Дополнительно добавлен config regression test, запрещающий нулевое/отрицательное `AUTO_TRAIN_RECOVERY_RETRY_MINUTES`.

## Реализация

### 1. Отдельный bootstrap/recovery trigger

`BackgroundTrainer.due_reason()` теперь сначала определяет usable-model recovery state:

- `bootstrap_recovery` — active non-baseline registry row существует, но ее artifact физически отсутствует и controlled fallback разрешен;
- `bootstrap_training` — active registry row отсутствует либо active model является deterministic baseline.

Оба состояния обходят требования ordinary dataset-change/new-timestamp trigger, но сохраняют обязательные проверки minimum history и symbol coverage.

### 2. Recovery episode identity

Предыдущий job считается частью того же bootstrap episode только если:

- его trigger равен `bootstrap_training` или `bootstrap_recovery`;
- `active_version` совпадает с текущим trigger.

Поэтому failure старого `scheduled_retraining` или `material_training_dataset_change` не задерживает новое восстановление после удаления модели.

### 3. Короткий технический backoff

Добавлена настройка:

```env
AUTO_TRAIN_RECOVERY_RETRY_MINUTES=15
```

Она применяется только после технического `FAILED` job того же bootstrap/recovery episode. Общий `AUTO_TRAIN_RETRY_HOURS` сохранен для обычных training cycles.

### 4. Защита от tight loop

Если recovery candidate успешно обучен и зарегистрирован, но `quality_gate_failed`, active baseline сохраняется. Следующая попытка использует `AUTO_TRAIN_DATA_CHANGE_COOLDOWN_HOURS`, а не 15-минутный technical retry.

Если auto-activation отключена или настроен operational override, применяются прежние более длинные scheduling semantics.

### 5. Сохраненные safety-инварианты

- candidate не активируется без quality gate;
- missing artifact не выдается за валидную ML-модель;
- SHA256 mismatch/corrupt/incompatible artifacts не переводятся в recovery missing-artifact path;
- PostgreSQL advisory lock не допускает параллельное обучение;
- stale registry row сохраняется до guarded activation;
- production fallback boundary не ослаблена.

## Измененные файлы

Production/config:

- `app/workers/trainer.py`;
- `app/config.py`;
- `.env.example`;
- `app/__init__.py`;
- `pyproject.toml`.

Tests:

- новый `tests/unit/test_trainer_recovery_scheduling.py`;
- `tests/unit/test_runtime_auth_config.py`.

Documentation:

- `README.md`;
- `CHANGELOG.md`;
- `PATCH_1.7.3.md`;
- `docs/CONFIGURATION.md`;
- `docs/INCIDENT_RUNBOOK.md`;
- `docs/MODEL_CARD.md`;
- `docs/OPERATOR_MANUAL.md`;
- `docs/QA_REPORT.md`;
- `docs/SPEC_COMPLIANCE.md`;
- `docs/TRACEABILITY.md`;
- данный отчет.

## Финальная проверка

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED (host environment) | внешний конфликт moviepy/pillow, не относящийся к declared dependencies проекта |
| `python -m compileall -q app scripts tests manage.py` | PASSED | без вывода |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 96 passed, 3 skipped |
| targeted recovery scheduler | PASSED | 7 passed |
| `node --check web/js/app.js` | PASSED | без вывода |
| `alembic heads` | PASSED | `0004_counterfactual_outcomes` |
| PostgreSQL integration | NOT RUN | отдельная PostgreSQL test database отсутствует |

## Миграция и совместимость

Новая migration не требуется. Existing `.env` остается валидным: default `AUTO_TRAIN_RECOVERY_RETRY_MINUTES=15` встроен в Settings. Для явной конфигурации рекомендуется добавить переменную в пользовательский `.env`.

Обновление:

```powershell
# сохранить существующие .env, models, reports и backups
python manage.py migrate
python manage.py run
```

Ожидаемое поведение при удаленном active artifact:

```text
worker: baseline-momentum-v1, DEGRADED
trainer after startup delay: bootstrap_recovery → LOADING_DATA → FITTING
```

Если история или coverage недостаточны, trainer остается в WAITING с точной причиной `not_enough_history_for_bootstrap` либо `insufficient_symbol_history_coverage`.

## Release boundary

Перед упаковкой удаляются:

- `.env` и credentials;
- `.venv`;
- `__pycache__`, `*.pyc`;
- `.pytest_cache`, `.ruff_cache`;
- `*.egg-info`, build/dist;
- dumps и реальные model artifacts.

Release содержит пустые `models`, `reports`, `backups` с `.gitkeep`.

## Текст коммита

```text
fix(trainer): start model recovery immediately from baseline

- detect missing active artifacts before normal dataset scheduling
- trigger bootstrap training when no usable ML model is available
- ignore unrelated prior job cooldowns for a new recovery episode
- add a short configurable retry backoff for technical recovery failures
- keep rejected candidates inactive and prevent tight retraining loops
- preserve absolute quality gates, guarded activation and production fail-closed behavior
- add recovery scheduler and configuration regression tests
- bump project version to 1.7.3
```

## Финальный архив

Имя и SHA-256 заполняются после окончательной очистки, пересчета `SHA256SUMS`, упаковки и повторной распаковки release.
