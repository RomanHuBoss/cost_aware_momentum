# QA Report — 1.52.1

Дата проверки: 2026-07-08.

## Окружение

- Python: 3.13.5.
- Project Python requirement: `>=3.12`.
- Node.js: доступен; `node --check` выполнен.
- Alembic head: `0018_inference_observations`.
- Проверки выполнялись из отдельного virtual environment `/mnt/data/cam_work/testenv`; project-local `.venv` намеренно не создавался.
- Безопасная отдельная PostgreSQL `TEST_DATABASE_URL` не была настроена; production/user database не использовалась.

## Baseline 1.52.0 до production-правок

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 846 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation | external venv не признаётся project-local runtime: `Виртуальная среда не найдена` |
| `python manage.py test --require-integration` | NOT RUN | wrapper остановился до тестов из-за отсутствия project-local `.venv`; безопасная PostgreSQL test DB также не настроена |

Входной ZIP содержал 270 файлов, 98 production/script Python-файлов, 120 test Python-файлов, 13 documentation-файлов и 18 Alembic revisions. Release-мусор, `.env`, caches, bytecode, virtual environments и `*.egg-info` во входном архиве не обнаружены.

## Red → green evidence

Новый regression module:

```text
tests/unit/test_fail_closed_incident_diagnostics_2026_07_08.py
```

Red-команда на исходном production code 1.52.0:

```bash
python -m pytest -q tests/unit/test_fail_closed_incident_diagnostics_2026_07_08.py
```

Red-результат: `3 failed`.

- generic `ValueError` не имел структурированного `capacity`;
- background trainer завершал ожидаемый дефицит истории как `FAILED` и `ERROR`;
- `JsonFormatter` отбрасывал `reason_code` и остальные безопасные contract diagnostics.

Green после исправления: `3 passed`.

Дополнительный scheduler regression test:

```text
tests/unit/test_trainer_recovery_scheduling.py::test_deferred_bootstrap_waits_for_new_training_data_after_cooldown
```

Он подтверждает, что `DEFERRED`-bootstrap не создаёт tight retry loop и ждёт новых timestamps или material profile change.

## Post-check 1.52.1

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 850 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation | external venv не признаётся project-local runtime: `Виртуальная среда не найдена` |
| `python manage.py test --require-integration` | NOT RUN | wrapper остановился до тестов из-за отсутствия project-local `.venv`; безопасная PostgreSQL test DB не настроена |
| `python -B manage.py release-check --write` | PASSED | clean manifest создан; после финального изменения docs пересчитан повторно |
| `python -B manage.py release-check` | PASSED | полный release contract и checksums подтверждены |
| ZIP integrity / clean re-extract | PASSED | архив протестирован, повторно распакован; один root и отсутствие запрещённых артефактов подтверждены |

## Warnings

62 существующих `DeprecationWarning` происходят преимущественно из `joblib`/NumPy shape semantics и pandas/NumPy timedelta semantics. Они не стали failures и не вызваны текущим patch, но требуют отдельной dependency-compatibility итерации до обновления библиотек, где warning может стать error.

## Scope statement

В 1.52.1 изменены только fail-closed walk-forward capacity/deferral и безопасная incident diagnostics. Ни один walk-forward fold, purge, holdout, feature, calibration, policy, experiment, cost-stress, EV/RR, risk или promotion threshold не снижен. Unit/static integrity не является доказательством прибыльности, экономической устойчивости или production readiness без PostgreSQL integration и forward evidence.
