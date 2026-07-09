# QA Report — 1.52.11

Дата проверки: 2026-07-09.

## Окружение

- Python: 3.13.5.
- Project Python requirement: `>=3.12`.
- Node.js: доступен; `node --check` выполнен.
- Alembic head: `0018_inference_observations`.
- Безопасная отдельная PostgreSQL `TEST_DATABASE_URL` не настроена; production/user database не использовалась.
- Shared sandbox имеет внешний конфликт `moviepy 2.2.1` ↔ `pillow 12.2.0`; это делает `python -m pip check` красным независимо от проекта.
- В raw sandbox отсутствовали `ruff` и `psycopg`; они были установлены как declared tooling/dependency для анализа текущего архива. Это не изменение проекта.

## Входной release 1.52.10

- ZIP: `cost_aware_momentum-main.zip`.
- SHA-256: `f01af1706cbbbc804760dbf1bb2485b4da314e87af426fa72df194866b37b1d2`.
- Исходная версия: 1.52.10.
- Alembic head: `0018_inference_observations`.

## Baseline 1.52.10 до правок

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | внешний conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE initially; PASSED after declared tool install | initial `No module named ruff`; unchanged code passed after tool install |
| `python -m pytest -q` | FAILED initially; NOT COMPLETED after declared dependency install | initial 62 collection errors from missing `psycopg`; after installing `psycopg`, full suite exceeded 600 s sandbox limit |
| `node --check web/js/app.js` | PASSED | exit 0 |
| focused quant/economics subset | PASSED | `111 passed in 7.40s` |
| `python manage.py release-check` after generated-cache cleanup | PASSED | `Release integrity PASSED: 295 files checked, 295 manifest entries` |
| `python manage.py doctor` | NOT RUN / environment precondition | project-local `.venv` missing; safe production/user DB was not used |
| `python manage.py test --require-integration` | NOT RUN / environment precondition | project-local `.venv` missing and separate PostgreSQL test DB not configured |

Baseline не считается зелёным: full suite, integration and environment dependency checks were not clean in this sandbox.

## Red → green evidence

New regression test:

```text
tests/unit/test_execution_acceptance_safety.py::test_acceptance_validator_rejects_current_entry_outside_signal_zone
```

Red evidence on 1.52.10 with the new test:

```text
E   Failed: DID NOT RAISE <class 'ValueError'>
```

Green after fix:

```bash
python -m pytest -q tests/unit/test_execution_acceptance_safety.py::test_acceptance_validator_rejects_current_entry_outside_signal_zone
```

Result: `1 passed in 4.37s`.

Focused post-check:

```bash
python -m pytest -q tests/unit/test_execution_acceptance_safety.py tests/unit/test_manual_entry_risk_integrity_2026_07_01.py tests/unit/test_orderbook_vwap_sizing_integrity_2026_07_08.py tests/unit/test_decision_anchor_entry_alignment_2026_07_07.py tests/unit/test_risk_math.py
```

Result: `97 passed in 6.00s`.

## Post-check 1.52.11

| Проверка | Статус | Результат |
|---|---|---|
| `python -m pip check` | FAILED / environment limitation | тот же внешний conflict `moviepy`/`pillow`, не вызван проектом |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | `All checks passed!` |
| `python -m pytest -q tests/unit/test_execution_acceptance_safety.py::test_acceptance_validator_rejects_current_entry_outside_signal_zone` | PASSED | `1 passed in 4.37s` |
| focused execution/risk suite | PASSED | `97 passed in 6.00s` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | NOT RUN / environment precondition | project-local `.venv` not configured in sandbox |
| `python manage.py test --require-integration` | NOT RUN / environment precondition | safe PostgreSQL `TEST_DATABASE_URL` not configured |
| `python manage.py release-check --write` | PASSED after cleanup | manifest rewritten for 1.52.11 |
| `python manage.py release-check` | PASSED after cleanup | release integrity verified |

## Scope statement

В 1.52.11 изменён только acceptance validation boundary for immutable decision-time entry zone. Risk formulas, signal selection math, model training thresholds, temporal split, holdout gates, promotion gates, Bybit read-only boundary, DB schema, migrations, `.env`, model-artifact schema, trainer logic and frontend UI не менялись. Static/unit integrity не является доказательством profitability, economic edge или production readiness без PostgreSQL integration, live read-only smoke и forward evidence.
