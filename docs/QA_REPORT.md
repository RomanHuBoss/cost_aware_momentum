# QA Report — 1.52.3

Дата проверки: 2026-07-08.

## Окружение

- Python: 3.13.5.
- Project Python requirement: `>=3.12`.
- Node.js: доступен; `node --check` выполнен.
- Alembic head: `0018_inference_observations`.
- Проверки выполнялись из отдельного isolated environment `/tmp/cam_lag/.venv`; project-local `.venv` намеренно не создавался.
- Безопасная отдельная PostgreSQL `TEST_DATABASE_URL` не настроена; production/user database не использовалась.

## Входной release 1.52.2

- ZIP: `cost_aware_momentum-1.52.2-orderbook-vwap-sizing.zip`.
- SHA-256: `6c2a57852410297823719c3105149562bea25df720fc7bff33b9de6a654623c5`.
- Состав по release manifest: 275 файлов.
- `.env`, secrets, caches, bytecode, virtual environments, `*.egg-info`, database dumps и реальные model artifacts во входном ZIP не обнаружены.

## Baseline 1.52.2 до production-правок

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 854 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation | external venv не признаётся project-local runtime: `Виртуальная среда не найдена` |
| `python manage.py test --require-integration` | NOT RUN | project-local `.venv` и безопасная PostgreSQL test DB не настроены |

## Red → green evidence

Новый regression module:

```text
tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py
```

Red-команда на неизменённом production code 1.52.2:

```bash
python -m pytest -q tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py
```

Red-результат: `3 failed`.

- `resolve_decision_publication_window` отсутствовал.
- `hourly_decision_cycle` не принимал `cycle_started_at` и не мог skip до тяжёлых jobs.
- `catchup_inference_job` не принимал explicit `checked_at` и не записывал terminal stale skip.

Green после исправления: `3 passed`.

Дополнительно стабилизированы existing catch-up tests, чтобы они проверяли fresh path с explicit within-window timestamp и не зависели от фактической минуты запуска тестов.

## Post-check 1.52.3

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 857 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation | external venv не признаётся project-local runtime: `Виртуальная среда не найдена` |
| `python manage.py test --require-integration` | NOT RUN | project-local `.venv` и безопасная PostgreSQL test DB не настроены |
| `python -B manage.py release-check --write` | PASSED | release files внесены в clean manifest |
| `python -B manage.py release-check` | PASSED | release contract, version agreement и checksums подтверждены |
| ZIP integrity / clean re-extract | PASSED | `unzip -t`, один root, 0 forbidden artifacts, internal release-check PASSED |

## Scope statement

В 1.52.3 изменена только scheduling/worker-семантика stale decision publication. Publication delay limit не увеличен, stale recommendations не публикуются, risk/math/model/Bybit contracts не менялись. Unit/static integrity не является доказательством прибыльности, economic edge или production readiness без PostgreSQL integration, live read-only smoke и forward evidence.
