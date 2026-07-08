# QA Report — 1.52.4

Дата проверки: 2026-07-08.

## Окружение

- Python: 3.13.5.
- Project Python requirement: `>=3.12`.
- Dependency QA set: NumPy 2.3.5, pandas 2.2.3, scikit-learn 1.7.2, pytest-asyncio 0.26.0.
- Node.js: доступен; `node --check` выполнен.
- Alembic head: `0018_inference_observations`.
- Проверки выполнялись в project-local `.venv` только для QA; `.venv` исключается из release ZIP.
- Безопасная отдельная PostgreSQL `TEST_DATABASE_URL` не настроена; production/user database не использовалась.

## Входной release 1.52.3

- ZIP: `cost_aware_momentum-1.52.3-stale-decision-publication.zip`.
- SHA-256: `21c5a98eb5a217c1d4eeb5a4fb7c0e7a8721ac4314e6f782bb84431e91239703`.
- Состав по release manifest: 278 файлов.
- `.env`, secrets, caches, bytecode, virtual environments, `*.egg-info`, database dumps и реальные model artifacts во входном ZIP не обнаружены.

## Baseline 1.52.3 до production-правок

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 857 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation | `.env` отсутствует, default secrets не заменены, `psql`/`pg_dump`/`pg_restore` не в PATH, PostgreSQL на localhost недоступен |
| `python manage.py test --require-integration` | NOT RUN | безопасная PostgreSQL test DB не настроена |

Дополнительно проверен fresh dependency risk: старый constraint `numpy>=2.1,<3` разрешал NumPy 2.5.1. В этом окружении существующий baseline падал на funding replay и policy phase tests (`10 failed, 847 passed, 8 skipped`). Поэтому release 1.52.4 ограничивает NumPy `<2.5` до отдельной совместимой адаптации.

## Red → green evidence

Новый regression test:

```text
tests/unit/test_trainer_recovery_scheduling.py::test_rejected_bootstrap_reports_new_data_wait_even_during_cooldown
```

Red-команда на неизменённом production code 1.52.3 с новым тестом:

```bash
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py::test_rejected_bootstrap_reports_new_data_wait_even_during_cooldown
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

Green-результат: `15 passed`.

## Post-check 1.52.4

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 858 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation | `.env` отсутствует, default secrets не заменены, `psql`/`pg_dump`/`pg_restore` не в PATH, PostgreSQL на localhost недоступен |
| `python manage.py test --require-integration` | NOT RUN | безопасная PostgreSQL test DB не настроена |
| `python -B manage.py release-check --write` | PASSED | release files внесены в clean manifest |
| `python -B manage.py release-check` | PASSED | release contract, version agreement и checksums подтверждены |
| ZIP integrity / clean re-extract | PASSED | `unzip -t`, один root, 0 forbidden artifacts, internal release-check PASSED |

## Scope statement

В 1.52.4 изменена только trainer scheduling diagnostics/UI и dependency upper bound для воспроизводимого QA. Trainer gates, quality thresholds, cooldown limits, API contract, migrations, risk/math/model/Bybit behavior не ослаблены. Unit/static integrity не является доказательством прибыльности, economic edge или production readiness без PostgreSQL integration, live read-only smoke и forward evidence.
