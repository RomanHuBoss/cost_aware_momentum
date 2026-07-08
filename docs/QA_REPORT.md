# QA Report — 1.52.6

Дата проверки: 2026-07-08.

## Окружение

- Python: 3.13.5.
- Project Python requirement: `>=3.12`.
- Dependency QA set in this sandbox: project dependencies were incomplete at first baseline (`psycopg` and `ruff` missing). For post static/unit checks, `psycopg[binary,pool]` and `ruff` were installed into the shared sandbox. The shared environment still has an unrelated `moviepy`/`pillow` conflict.
- Node.js: доступен; `node --check` выполнен.
- Alembic head: `0018_inference_observations`.
- Безопасная отдельная PostgreSQL `TEST_DATABASE_URL` не настроена; production/user database не использовалась.

## Входной release 1.52.5

- ZIP: `cost_aware_momentum-main(1).zip`.
- SHA-256: `5e51ea6dc48ded4cf7f4695f2a17a04015ebeccd72a02acfadb31ce84b9c2a51`.
- Исходная версия: 1.52.5.
- Состав после распаковки: один root directory; 99 production-ish files, 123 test files, 27 documentation/top-level markdown files.
- `.env`, virtualenv, build/dist, `*.egg-info`, реальные model artifacts и dumps во входном ZIP не обнаружены. Локальные `__pycache__`/`.pytest_cache` появились только после проверок и исключены из итогового ZIP.

## Baseline 1.52.5 до production-правок

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | Shared environment conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` before dependency install |
| `python -m pytest -q` | FAILED / environment limitation | collection interrupted with `61 errors`; primary cause: `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | NOT RUN in baseline | delayed until post checks; project-local `.venv` was not present |
| `python manage.py test --require-integration` | NOT RUN in baseline | safe PostgreSQL test DB was not configured |

## Red → green evidence

Новые regression tests:

```text
tests/unit/test_initial_training_backfill_readiness_2026_07_08.py::test_default_initial_backfill_covers_training_quality_gate_precondition
tests/unit/test_initial_training_backfill_readiness_2026_07_08.py::test_sync_candles_paginates_initial_backfill_beyond_bybit_page_limit
```

Red-команда после добавления тестов на неизменённом production code 1.52.5:

```bash
python -m pytest -q tests/unit/test_initial_training_backfill_readiness_2026_07_08.py
```

Red-результат: `2 failed`.

Существенные строки:

```text
E       AssertionError: assert 1000 >= 1206
E       assert 1000 == 1206
```

Green после исправления:

```bash
python -m pytest -q tests/unit/test_initial_training_backfill_readiness_2026_07_08.py
```

Green-результат: `2 passed`.

## Post-check 1.52.6

| Проверка | Статус | Результат |
|---|---|---|
| `python -m pip check` | FAILED / environment limitation | тот же внешний conflict `moviepy`/`pillow`, не вызван проектом |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| targeted regression suite | PASSED | `20 passed` |
| `python -m pytest -q` | PASSED | `861 passed, 8 skipped in 27.87s` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py release-check --write && python manage.py release-check` | PASSED | `Release integrity PASSED: 285 files checked, 285 manifest entries` |
| `python manage.py doctor` | FAILED / environment limitation | `Виртуальная среда не найдена. Сначала выполните: python manage.py setup` |
| `python manage.py test --require-integration` | FAILED / environment limitation | command blocked by absent project-local `.venv`; safe PostgreSQL `TEST_DATABASE_URL` not configured |

Full suite command:

```bash
python -m pytest -q
```

Full suite result: `861 passed, 8 skipped in 27.87s`.

Targeted regression suite command:

```bash
python -m pytest -q \
  tests/unit/test_initial_training_backfill_readiness_2026_07_08.py \
  tests/unit/test_historical_dynamic_bootstrap_2026_07_07.py \
  tests/unit/test_walk_forward_validation_2026_07_05.py \
  tests/unit/test_hourly_candle_retry_2026_07_04.py \
  tests/unit/test_candle_availability_integrity_2026_07_03.py
```

## Scope statement

В 1.52.6 изменена только startup/backfill readiness path: default depth and kline pagination for `sync_candles()`. Risk math, model thresholds, temporal split, holdout gates, policy gates, promotion gates, Bybit private/read-only boundary, API schemas and migrations не менялись. Unit/static integrity не является доказательством прибыльности, economic edge или production readiness без PostgreSQL integration, live read-only smoke и forward evidence.
