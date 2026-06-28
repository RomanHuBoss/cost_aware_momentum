# Patch 1.7.1 — JSON-safe model candidate registration

## Исправленная проблема

После успешного fitting trainer мог создать immutable `.joblib`, но завершить job со статусом `FAILED` до регистрации кандидата. Подтвержденная ошибка PostgreSQL:

```text
psycopg.errors.InvalidTextRepresentation: неверный синтаксис для типа json
DETAIL: Ошибочный элемент "-Infinity".
CONTEXT: ... "incumbent_policy_realized_mean_r": -Infinity ...
```

Причина: при отсутствии policy-сделок у incumbent quality gate использовал `-math.inf` как внутренний fail-closed sentinel и затем помещал это значение в `ModelRegistry.metrics` JSONB. PostgreSQL JSONB принимает только строгие JSON-числа и отклоняет `NaN`, `Infinity` и `-Infinity`.

## Изменения

- `evaluate_quality_gate()` по-прежнему использует внутренние sentinel-значения для тех же сравнений и причин отклонения, но наружу возвращает только конечные числа либо `null`.
- Non-finite relative deltas также сохраняются как `null`; flags `ml_improved`, `policy_improved` и итоговый `passed` вычисляются по прежней fail-closed логике.
- Новый `app/json_utils.py` рекурсивно нормализует JSON payload, включая NumPy scalars, `NaN` и `±Infinity`.
- Защитная нормализация применяется перед записью:
  - model registry metrics;
  - trainer job details;
  - trainer heartbeat details;
  - audit payload;
  - outbox payload.
- Audit canonical JSON теперь формируется с `allow_nan=False`.

## Совместимость

- PostgreSQL schema и Alembic head не изменены.
- `.env` и `.env.example` не требуют новых параметров.
- Активная модель не меняется при обновлении.
- Уже созданный orphan artifact не регистрируется и не активируется автоматически; следующий training cycle создаст и зарегистрирует новый candidate.
- Пороговые значения quality gate не ослаблены.

## Проверка

Red до исправления:

```text
2 failed
ValueError: Out of range float values are not JSON compliant: -inf
```

Green после исправления:

```text
77 passed, 3 skipped
Ruff: passed
compileall: passed
node --check: passed
```
