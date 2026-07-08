# QA Report — 1.52.8

Дата проверки: 2026-07-08.

## Окружение

- Python: 3.13.5.
- Project Python requirement: `>=3.12`.
- Node.js: доступен; `node --check` выполнен.
- Alembic head: `0018_inference_observations`.
- Безопасная отдельная PostgreSQL `TEST_DATABASE_URL` не настроена; production/user database не использовалась.
- Shared sandbox имеет внешний конфликт `moviepy 2.2.1` ↔ `pillow 12.2.0`; это делает `python -m pip check` красным независимо от проекта.
- Для воспроизводимого baseline были установлены заявленные зависимости `psycopg[binary,pool]` и `ruff`, отсутствовавшие в sandbox до правок.

## Входной release 1.52.7

- ZIP: `cost_aware_momentum-main.zip`.
- SHA-256: `9cbd4854ee0d342294f3a9f3bdb6ba70bf3af6261cc5c1e68c4458cceac9d44e`.
- Исходная версия: 1.52.7.
- Alembic head: `0018_inference_observations`.

## Baseline 1.52.7 до production-правок

Первый baseline до установки недостающих declared dependencies:

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | Shared environment conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | `No module named ruff` |
| `python -m pytest -q` | FAILED / environment limitation | 61 collection errors from missing declared dependency `psycopg` |
| `node --check web/js/app.js` | PASSED | exit 0 |

Runnable baseline after installing declared dependencies, still before code changes:

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | same external `moviepy` / `pillow` conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | `863 passed, 8 skipped in 18.03s` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | NOT RUN | project-local `.venv` and safe app runtime config were not present before changes |
| `python manage.py test --require-integration` | NOT RUN | safe PostgreSQL test DB was not configured before changes |

## Red → green evidence

Новые/обновленные regression tests:

```text
tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py::test_repeated_stale_catchup_is_suppressed_until_next_event_hour
tests/unit/test_trainer_status_diagnostics_2026_07_08.py::test_trainer_wait_reason_prefers_heartbeat_contract
tests/unit/test_trainer_status_diagnostics_2026_07_08.py::test_trainer_wait_reason_derives_direction_label_failure_from_latest_job
tests/unit/test_trainer_operator_ui.py::test_operator_ui_exposes_trainer_status_dialog_and_safe_controls
```

Red evidence on 1.52.7 with new tests:

- `test_trainer_status_diagnostics_2026_07_08.py`: import error because `trainer_effective_wait_reason` did not exist.
- `test_repeated_stale_catchup_is_suppressed_until_next_event_hour`: failed because duplicate same-hour catch-up returned another `decision_publication_lag_exceeded`.
- `test_trainer_operator_ui.py`: failed because `no_direction_specific_barrier_labels` and `effective_wait_reason` were absent from UI code.

Green after fix:

```bash
python -m pytest -q \
  tests/unit/test_trainer_status_diagnostics_2026_07_08.py \
  tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py::test_repeated_stale_catchup_is_suppressed_until_next_event_hour \
  tests/unit/test_trainer_operator_ui.py
```

Result: `4 passed in 4.09s`.

## Post-check 1.52.8

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | тот же внешний conflict `moviepy`/`pillow`, не вызван проектом |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | `866 passed, 8 skipped in 18.13s` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python scripts/release_integrity.py` after cache cleanup and manifest rewrite | PASSED | `Release integrity PASSED: 290 files checked, 290 manifest entries.` |
| `python manage.py doctor` | FAILED / environment precondition | project-local `.venv` missing: `Виртуальная среда не найдена. Сначала выполните: python manage.py setup` |
| `python manage.py test --require-integration` | FAILED / environment precondition | project-local `.venv` missing before integration dispatch |

## Scope statement

В 1.52.8 изменён только worker/status/UI diagnostics path: duplicate stale catch-up suppression and derived trainer wait reason from persisted training failure. Risk math, model thresholds, temporal split, holdout gates, policy gates, promotion gates, Bybit private/read-only boundary, DB schema, migrations, `.env` and model-artifact schema не менялись. Unit/static integrity не является доказательством прибыльности, economic edge или production readiness без PostgreSQL integration, live read-only smoke и forward evidence.
