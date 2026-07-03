# QA Report — 1.9.1

Дата: 2026-07-03

## Входной архив

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `0817de47461ad67551cab98a85216148bc3f5c71a34f3ad725e1125fec38f566`.
- Исходная версия: `1.9.0`; Python requirement: `>=3.12`.
- Исходный состав: 70 production/maintenance Python files (включая `manage.py`), 51 `test_*.py` modules, 18 Markdown files в `docs/`.
- Исходный Alembic head: `0008_outcome_path_unavailable`.
- В архиве не обнаружены `.env`, secrets, virtualenv, caches, dumps или реальные model artifacts.
- Утверждения о количестве ошибок не сопровождались модулями, stack traces или reproductions; severity присвоена только воспроизведённому дефекту.

## Baseline до правок

Системное окружение не являлось project environment: отсутствовали `ruff` и `psycopg`, а глобальный `pip check` содержал посторонний конфликт `moviepy/Pillow`. Этот запуск зафиксирован как environment failure, не как дефект проекта.

Повторный baseline выполнен в изолированном virtualenv после `pip install -e '.[dev]'`:

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5; requirement `>=3.12` выполнен |
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **432 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0008_outcome_path_unavailable` |
| `python manage.py doctor` | NOT RUN | operator `.env` и project PostgreSQL отсутствуют |
| `python manage.py test --require-integration` | NOT RUN | `TEST_DATABASE_URL` и PostgreSQL client/server отсутствуют; user/production DB не использовалась |

Warnings — third-party NumPy/joblib deprecations в serialization tests.

## Подтверждённый дефект

### HIGH — late candle backfill appeared historically available

Production path: `app/services/market_data.py::_candle_values`, вызываемый `sync_candles`, `sync_candle_history` и `sync_candle_windows`.

Фактическое поведение до исправления:

```text
close_time = open_time + interval
available_at = close_time
confirmed = close_time <= response_received_at
```

Если часовая свеча закрылась в 09:00, но была впервые загружена в 12:00, запись утверждала `available_at=09:00`. Запросы point-in-time replay уже корректно применяли `Candle.available_at <= availability_cutoff`, но неверное значение позволяло использовать поздний backfill задним числом. Это temporal leakage и прямое нарушение разделения event time / availability time из спецификации.

Влияние:

- исторический replay мог видеть свечу до фактического получения;
- research/econometric evidence мог быть завышен;
- результаты до/после backfill могли быть невоспроизводимы;
- существующий тест закреплял неправильный oracle `available_at==close_time`.

## Исправление

- `_candle_values` сохраняет `available_at=now`, где `now` фиксируется после завершения Bybit response.
- `confirmed` продолжает зависеть от `close_time <= receipt_time`.
- Confirmed candle остаётся immutable; open candle может обновляться до первого confirmed snapshot.
- Migration `0009_candle_receipt_availability` выполняет:

```sql
UPDATE market.candles
SET available_at = GREATEST(available_at, CURRENT_TIMESTAMP)
WHERE confirmed IS TRUE;
```

- Точные legacy receipt timestamps не реконструируются. Сдвиг к моменту migration намеренно консервативен и fail-closed.
- Downgrade не возвращает ошибочные timestamps; data correction остаётся совместимой с 1.9.0.

## Red → green

До production change:

```text
python -m pytest -q tests/unit/test_candle_availability_integrity_2026_07_03.py
2 failed
```

Причины:

1. late-fetched candle имел `available_at=close_time`, а не `response_received`;
2. migration `0009_candle_receipt_availability.py` отсутствовала.

После исправления:

```text
python -m pytest -q \
  tests/unit/test_candle_availability_integrity_2026_07_03.py \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py \
  tests/unit/test_migration_revision_contract.py
12 passed
```

## Post-check

| Проверка | Статус | Результат |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed after import fix |
| `python -m pytest -q` | PASSED | **434 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head: `0009_candle_receipt_availability` |
| `python -m alembic upgrade head --sql` | PASSED | complete offline SQL generated, including migration 0009 |
| PostgreSQL integration | NOT RUN | isolated database unavailable |
| `python manage.py doctor` | NOT RUN | no local operator configuration/database |

## Compatibility and operator actions

- Version: `1.9.1` patch release.
- New `.env` variables: none.
- Database migration: required, head `0009_candle_receipt_availability`.
- Artifact/policy schemas: unchanged; retraining is not required solely by this patch.
- Before update: backup PostgreSQL and stop API/worker/trainer.
- After replacement: run `python manage.py release-check`, `python manage.py migrate`, then `python manage.py doctor` and restart.

## Residual risks

- Real PostgreSQL upgrade/downgrade and data-update row counts were not verified in this environment.
- Exact receipt time of legacy candles is unknowable; migration uses a conservative upper bound.
- Historical order book, actual fills, operator latency, exact funding timeline, full rolling walk-forward, drift governance and PBO/DSR remain incomplete.
- Source-only audit cannot explain particular losing trades without the running PostgreSQL state, candidate metrics, signal/plan snapshots and manual fills.
- Passing tests and corrected temporal semantics do not establish profitability.
