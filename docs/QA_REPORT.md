# QA Report — 1.8.26

Дата: 2026-07-01

## Входной baseline 1.8.25

Архив: `cost_aware_momentum-main.zip`
SHA-256: `39f1a1f875b139fb4ff074018c4e74bca061b13fa5c2e73bc4128c6ed31d9e85`

Глобальный Python 3.13.5 не использовался как доказательство качества: `pip check` обнаружил посторонний конфликт Pillow/MoviePy, `ruff` отсутствовал, а pytest не собирался без `psycopg`.

В изолированном окружении `/mnt/data/cam_venv` до правок:

| Проверка | Результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 371 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | NOT RUN — исходный проект не содержит project-local `.venv`/`.env`; `manage.py` корректно остановился с требованием `setup` |
| `python manage.py test --require-integration` | NOT RUN — project-local `.venv` отсутствует |

## Red → green

| Контракт | Red на 1.8.25 | Green на 1.8.26 |
|---|---|---|
| Текущий ask/bid является entry execution plan | `test_execution_plan_reprices_from_current_executable_quote` failed: snapshot сохранял `100`, а не ask `100.4` | PASSED |
| Missing bid/ask блокирует план | `test_execution_plan_fails_closed_when_executable_quote_is_missing` failed: `ACTIONABLE` | PASSED: `BLOCKED_DATA` |
| Цена вне entry-zone не actionable | `test_execution_plan_marks_quote_outside_entry_zone_as_no_trade` failed: `ACTIONABLE` | PASSED: `NO_TRADE` |
| Terminal signal status имеет приоритет | `test_terminal_signal_status_is_not_overwritten_by_liquidation_diagnostic` failed: `BLOCKED_LIQUIDATION` вместо `EXPIRED` | PASSED |
| Negative minimum EV запрещен | `test_negative_minimum_net_ev_is_rejected` failed: exception отсутствовало | PASSED |
| Auto-activation не допускает negative realized mean R | parametrized test failed: exception отсутствовало | PASSED |
| Auto-activation не допускает PF < 1 | parametrized test failed: exception отсутствовало | PASSED |

Red execution command: 4 failed, 34 deselected.
Red configuration command: 3 failed, 1 passed.
Targeted green: 38 passed.

## Post-check 1.8.26

| Проверка | Результат |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 379 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0007_position_account_scope` |
| Independent Decimal economics audit | PASSED — 10,000 randomized cases |
| Independent label/live barrier parity audit | PASSED — 5,000 randomized cases |
| `python -m scripts.test_runner --require-integration` | NOT RUN — безопасно остановлен: `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` не заданы |
| PostgreSQL migration/audit integration suite | NOT RUN |

19 warnings относятся к joblib/NumPy 2.5 deprecation в artifact tests и не являются новыми regression failures.

Release integrity, manifest count, повторная распаковка и SHA-256 финального ZIP фиксируются после очистки и упаковки release tree.
