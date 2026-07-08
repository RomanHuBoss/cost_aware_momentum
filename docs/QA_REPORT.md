# QA Report — 1.52.10

Дата проверки: 2026-07-08.

## Окружение

- Python: 3.13.5.
- Project Python requirement: `>=3.12`.
- Node.js: доступен; `node --check` выполнен.
- Alembic head: `0018_inference_observations`.
- Безопасная отдельная PostgreSQL `TEST_DATABASE_URL` не настроена; production/user database не использовалась.
- Shared sandbox имеет внешний конфликт `moviepy 2.2.1` ↔ `pillow 12.2.0`; это делает `python -m pip check` красным независимо от проекта.
- В sandbox отсутствуют declared dev/runtime dependencies `ruff` и `psycopg`; full `pytest -q` останавливается на collection import errors до выполнения suite.

## Входной release 1.52.9

- ZIP: `cost_aware_momentum-1.52.9-trainer-progress-clarity.zip`.
- SHA-256: `36bcdbedaf8e6b5171e09850dd15002b4ed6b5dba01fdfae805793a54aeaa2f7`.
- Исходная версия: 1.52.9.
- Alembic head: `0018_inference_observations`.

## Baseline 1.52.9 до правок

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | внешний conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED / environment limitation | 62 collection errors from missing declared dependency `psycopg` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | FAILED / environment precondition | project-local `.venv` missing: `Виртуальная среда не найдена. Сначала выполните: python manage.py setup` |
| `python manage.py test --require-integration` | FAILED / environment precondition | project-local `.venv` missing before integration dispatch; safe PostgreSQL test DB not configured |

Baseline не считается зелёным: часть проверок недоступна или падает из-за shared sandbox dependencies.

## Red → green evidence

Новые regression tests:

```text
tests/unit/test_signal_economics_diagnostics_2026_07_08.py::test_json_formatter_preserves_signal_economics_skip_context
tests/unit/test_signal_economics_diagnostics_2026_07_08.py::test_invalid_signal_economics_skip_is_classified_in_diagnostics
```

Red evidence on 1.52.9 with the new tests:

```text
KeyError: 'reason_detail'
AssertionError: {'invalid_signal_economics': 1} != {'quote_outside_decision_entry_zone': 1}
```

Green after fix:

```bash
python -m pytest -q tests/unit/test_signal_economics_diagnostics_2026_07_08.py
```

Result: `2 passed`.

Additional focused regression check:

```bash
python -m pytest -q tests/unit/test_signal_economics_diagnostics_2026_07_08.py tests/unit/test_attrition_inference_instrumentation_2026_07_05.py
```

Result: `3 passed`.

## Post-check 1.52.10

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | тот же внешний conflict `moviepy`/`pillow`, не вызван проектом |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED / environment limitation | collection fails from missing declared dependency `psycopg` before suite execution |
| `python -m pytest -q tests/unit/test_signal_economics_diagnostics_2026_07_08.py` | PASSED | `2 passed` |
| `python -m pytest -q tests/unit/test_signal_economics_diagnostics_2026_07_08.py tests/unit/test_attrition_inference_instrumentation_2026_07_05.py` | PASSED | `3 passed` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment precondition | project-local `.venv` missing: `Виртуальная среда не найдена. Сначала выполните: python manage.py setup` |
| `python manage.py test --require-integration` | FAILED / environment precondition | project-local `.venv` missing before integration dispatch; safe PostgreSQL test DB not configured |
| `python -B -m scripts.release_integrity --write` | PASSED | `Release integrity PASSED` after manifest rewrite |

## Scope statement

В 1.52.10 изменён только diagnostics path for fail-closed signal-economics skips. Risk math, model thresholds, temporal split, holdout gates, policy gates, promotion gates, Bybit private/read-only boundary, DB schema, migrations, `.env`, model-artifact schema, trainer logic and frontend UI не менялись. Static/unit integrity не является доказательством прибыльности, economic edge или production readiness без PostgreSQL integration, live read-only smoke и forward evidence.
