# Итерационный отчет: JSON-safe model registry lifecycle

Дата: 28 июня 2026 г.  
Версия после изменения: 1.7.1

## Цель

После этой итерации background trainer должен регистрировать каждый успешно обученный immutable candidate как неактивную запись PostgreSQL даже тогда, когда у incumbent либо candidate отсутствуют policy-сделки и соответствующие метрики равны `None`. Это подтверждается strict-JSON regression tests и полным unit test suite.

## Вход и baseline

- Входной архив: `cost_aware_momentum-1.7.0-intrabar-outcomes.zip`.
- SHA-256: `58e1270f61c0d6efc8e731790e8a5cbe673278d021fe61e7b2d3db9bd80732b6`.
- Версия пакета/приложения: 1.7.0.
- Python requirement: `>=3.12`.
- Alembic head: `0004_counterfactual_outcomes`.
- Production files: 67; test files: 14; documentation files: 13.
- Release-артефакты `.env`, secrets, `.venv`, caches, `*.pyc`, `*.egg-info`, dumps и реальные model artifacts отсутствовали.

Baseline checks:

| Проверка | Статус |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | FAILED (host environment) — установленный вне проекта `moviepy 2.2.1` конфликтует с host `pillow 12.2.0`; зависимости проекта не являются причиной |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED после установки declared dev tool в host environment |
| `python -m pytest -q` | PASSED — 74 passed, 3 skipped |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | NOT RUN — отсутствуют пользовательский `.env`, native PostgreSQL service/tools и безопасные credentials |
| `python manage.py test --require-integration` | NOT RUN — отсутствует отдельная PostgreSQL test database |

## Подтвержденный дефект

Классификация: `CONFIRMED DEFECT`, severity `high`.

Пользовательский `ops.job_runs` зафиксировал:

```text
psycopg.errors.InvalidTextRepresentation
неверный синтаксис для типа json
Ошибочный элемент "-Infinity"
... "incumbent_policy_realized_mean_r": -Infinity ...
```

Путь данных:

```text
incumbent без actionable policy trades
→ evaluate_policy_model(): policy_realized_mean_r = None
→ evaluate_quality_gate(): внутренний sentinel -math.inf
→ quality_gate.relative.incumbent_policy_realized_mean_r = -Infinity
→ register_model_candidate(): ModelRegistry.metrics JSONB
→ PostgreSQL отвергает INSERT
→ artifact уже сохранен, candidate не зарегистрирован, job FAILED
```

Влияние:

- создается orphan `.joblib`;
- registry и audit не содержат candidate;
- active-модель остается безопасно неизменной, но trainer повторяет дорогое обучение после cooldown;
- оператор видит более свежий файл, который невозможно штатно активировать или исследовать через registry.

Существующие тесты проверяли gate decisions, но не строгую JSON-сериализуемость результатов при отсутствии policy-сделок.

## Red → green

До production fix добавлены два теста:

```text
test_quality_gate_remains_strict_json_when_incumbent_has_no_policy_trades
test_quality_gate_serializes_missing_candidate_policy_metrics_as_null
```

Red:

```text
2 failed
ValueError: Out of range float values are not JSON compliant: -inf
```

Green после исправления:

```text
7 passed
```

Дополнительно добавлен тест рекурсивной нормализации nested `NaN`, `±Infinity` и NumPy scalars.

## Реализация

### `app/ml/lifecycle.py`

- внутренние `±math.inf` сохранены только как локальные значения для fail-closed comparison;
- сериализуемые absolute/relative metrics содержат finite number либо `None`;
- non-finite delta сохраняется как `null`, а boolean decision flags вычисляются по прежней логике;
- model registry metrics нормализуются непосредственно перед PostgreSQL INSERT.

### `app/json_utils.py`

Добавлена рекурсивная функция `json_compatible()` для:

- `NaN`, `Infinity`, `-Infinity` → `None`;
- NumPy scalar → native JSON scalar;
- nested mappings/sequences;
- UUID/Path/date/time/Enum/Decimal.

Неподдерживаемый тип вызывает исключение вместо silent fallback.

### JSONB boundaries

Нормализация добавлена к model registry, trainer job details, trainer heartbeat, audit и outbox. Audit hash формируется strict JSON encoder с `allow_nan=False`.

## Совместимость и rollback

- Migration не требуется.
- Публичный API и `.env` contract не изменены.
- Advisory-only, PostgreSQL-only, process separation и active-model safety сохранены.
- Gate thresholds не ослаблены.
- Rollback: вернуть 1.7.0 source files; schema rollback не требуется. Это вернет дефект, поэтому rollback допустим только как кратковременная диагностика.

## Post-check

| Проверка | Статус |
|---|---|
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 77 passed, 3 skipped |
| targeted lifecycle/json tests | PASSED — 7 passed |
| `node --check web/js/app.js` | PASSED |
| Alembic head | unchanged — `0004_counterfactual_outcomes` |

## Операционное действие после обновления

1. Остановить текущие API/worker/trainer процессы.
2. Заменить файлы проекта, сохранив пользовательский `.env`, PostgreSQL data, `models/`, `reports/` и `backups/`.
3. Выполнить `python manage.py migrate` — изменений схемы нет, команда должна подтвердить текущий head.
4. Запустить `python manage.py run`.
5. После следующей попытки проверить `python manage.py model-registry list`: новый candidate должен присутствовать как `active=false`, если gate не пройден, либо стать active только при полном gate pass.
6. Старый orphan `barrier-logistic-h8-20260627T212102Z.joblib` не активировать вручную; его можно оставить для аудита или удалить после появления корректно зарегистрированного кандидата.

## Commit message

```text
fix(trainer): keep quality-gate metrics JSON-safe

- separate fail-closed sentinels from serialized gate values
- store missing and non-finite metrics as JSON null
- normalize registry, trainer, audit and outbox JSON payloads
- enforce strict JSON encoding for audit hashes
- add regression tests for zero-trade incumbent metrics
```
