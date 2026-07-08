# QA Report — 1.52.5

Дата проверки: 2026-07-08.

## Окружение

- Python: 3.13.5.
- Project Python requirement: `>=3.12`.
- Dependency QA set in this sandbox: NumPy 2.3.5, pandas 2.2.3, scikit-learn 1.8.0, pytest-asyncio 1.3.0 present from the shared environment; project runtime dependencies installed from `pyproject.toml`.
- Node.js: доступен; `node --check` выполнен.
- Alembic head: `0018_inference_observations`.
- Безопасная отдельная PostgreSQL `TEST_DATABASE_URL` не настроена; production/user database не использовалась.

## Входной release 1.52.4

- ZIP: `cost_aware_momentum-main.zip`.
- SHA-256: `1e3e0c117e3c47c616c113adbcc061c7f003dd9972217a55c1ba2ef69a99cbf4`.
- Исходная версия: 1.52.4.
- Состав после распаковки: один root directory, 281 файлов до локального `compileall`.
- `.env`, virtualenv, build/dist, `*.egg-info`, реальные model artifacts и dumps во входном ZIP не обнаружены; локальные `__pycache__`/`.pytest_cache` появились только после проверок и исключены из итогового ZIP.

## Baseline 1.52.4 до production-правок

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | Shared environment conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0`; также warning об invalid external `~ytest` distribution после частичной переустановки pytest |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | NOT COMPLETED | В shared environment full suite не завершил процесс в доступном timeout; до остановки шли unit tests без failure summary. Это не отмечено как PASSED |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation | `manage.py` требует project-local `.venv`; локальная PostgreSQL/.env не настроены |
| `python manage.py test --require-integration` | NOT RUN / environment limitation | безопасная PostgreSQL test DB не настроена; команда также блокируется отсутствием project-local `.venv` |

## Red → green evidence

Новый regression test:

```text
tests/unit/test_trainer_recovery_scheduling.py::test_rejected_bootstrap_recovers_profile_from_candidate_metrics
```

Red-команда после добавления теста на неизменённом production code 1.52.4:

```bash
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py::test_rejected_bootstrap_recovers_profile_from_candidate_metrics
```

Red-результат: `1 failed`.

Существенная строка:

```text
E       AssertionError: assert 'training_cooldown_not_elapsed' == 'quality_gate_failed_waiting_for_new_data'
```

Green после исправления:

```bash
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py tests/unit/test_trainer_operator_ui.py
```

Green-результат: `16 passed`.

## Post-check 1.52.5

| Проверка | Статус | Результат |
|---|---|---|
| `python -m pip check` | FAILED / environment limitation | тот же внешний conflict `moviepy`/`pillow`, не вызван проектом |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py tests/unit/test_trainer_operator_ui.py` | PASSED | 16 passed |
| `python -m pytest -q` | NOT COMPLETED | full suite в shared environment завис/не завершил процесс в доступном timeout; не заявляется как passed |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation | project-local `.venv`/PostgreSQL/.env отсутствуют |
| `python manage.py test --require-integration` | NOT RUN / environment limitation | safe PostgreSQL `TEST_DATABASE_URL` не настроена; command blocked by absent project-local `.venv` |

## Scope statement

В 1.52.5 изменена только trainer scheduling diagnostics для извлечения уже persisted previous training profile из candidate metrics. Risk math, Bybit client, API schemas, migrations, thresholds, quality/promotion gates и advisory-only boundary не менялись. Unit/static integrity не является доказательством прибыльности, economic edge или production readiness без PostgreSQL integration, live read-only smoke и forward evidence.
