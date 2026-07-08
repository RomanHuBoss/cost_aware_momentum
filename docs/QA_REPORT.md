# QA Report — 1.52.7

Дата проверки: 2026-07-08.

## Окружение

- Python: 3.13.5.
- Project Python requirement: `>=3.12`.
- Node.js: доступен; `node --check` выполнен.
- Alembic head: `0018_inference_observations`.
- Безопасная отдельная PostgreSQL `TEST_DATABASE_URL` не настроена; production/user database не использовалась.
- Shared sandbox имеет внешний конфликт `moviepy 2.2.1` ↔ `pillow 12.2.0`; это делает `python -m pip check` красным независимо от проекта.

## Входной release 1.52.6

- ZIP: `cost_aware_momentum-1.52.6-startup-training-backfill.zip`.
- SHA-256: `02733885af0bfe0ba22f14ed4534c237f6dd2b044a18b2a586d9ff7950641c0a`.
- Исходная версия: 1.52.6.
- Alembic head: `0018_inference_observations`.

## Baseline 1.52.6 до production-правок

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | Shared environment conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | NOT RUN to completion | one all-in-one run timed out in the sandbox; chunked unit suite was used post-change |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | NOT RUN | project-local `.venv` not present |
| `python manage.py test --require-integration` | NOT RUN | safe PostgreSQL test DB was not configured |

## Red → green evidence

Новые regression tests:

```text
tests/unit/test_initial_training_backfill_readiness_2026_07_08.py::test_default_open_interest_history_backfill_covers_training_quality_gate_precondition
tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py::test_repeated_stale_hourly_cycle_is_suppressed_until_next_event_hour
```

Red-команда на production code 1.52.6 после добавления тестов:

```bash
python -m pytest -q \
  tests/unit/test_initial_training_backfill_readiness_2026_07_08.py::test_default_open_interest_history_backfill_covers_training_quality_gate_precondition \
  tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py::test_repeated_stale_hourly_cycle_is_suppressed_until_next_event_hour
```

Red-результат: `2 failed`.

Существенные строки:

```text
AttributeError: 'Settings' object has no attribute 'history_backfill_open_interest_pages_per_symbol'
AttributeError: type object 'Worker' has no attribute 'hourly_decision_cycle_if_due'
```

Green после исправления:

```bash
python -m pytest -q \
  tests/unit/test_initial_training_backfill_readiness_2026_07_08.py \
  tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py
```

Green-результат: `7 passed`.

## Post-check 1.52.7

| Проверка | Статус | Результат |
|---|---|---|
| `python -m pip check` | FAILED / environment limitation | тот же внешний conflict `moviepy`/`pillow`, не вызван проектом |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| targeted regression suite | PASSED | `7 passed` |
| `python -m pytest -q tests/unit` | PASSED in chunks | `863 passed` across five deterministic chunks; one all-in-one run timed out in the sandbox before completion |
| `python -m pytest -q tests/integration_postgres` | SKIPPED | `8 skipped` because safe PostgreSQL integration DB was not configured |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | NOT RUN | project-local `.venv` not present |
| `python manage.py test --require-integration` | NOT RUN | safe PostgreSQL `TEST_DATABASE_URL` not configured |

Chunked unit suite evidence:

```text
chunk 1: 168 passed
chunk 2: 200 passed
chunk 3: 155 passed
chunk 4: 202 passed
chunk 5: 138 passed
```

## Scope statement

В 1.52.7 изменён только worker/backfill readiness path: отдельная open-interest history depth, status diagnostics и suppression повторного stale-hourly skip для одного event hour. Risk math, model thresholds, temporal split, holdout gates, policy gates, promotion gates, Bybit private/read-only boundary, DB schema, migrations and model-artifact schema не менялись. Unit/static integrity не является доказательством прибыльности, economic edge или production readiness без PostgreSQL integration, live read-only smoke и forward evidence.
