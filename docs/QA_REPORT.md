# QA Report — 1.9.5

Дата: 2026-07-04

## Входной архив

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `faee7d0f484848c34c33970aa8be950e95782116d0e0fbd449d55f799b0afa6e`.
- Исходная версия: `1.9.4`; Python requirement: `>=3.12`.
- Исходный состав: 74 files в `app/`, `scripts/`, `web/`; 85 вместе с migrations; 56 test files, из них 55 `test_*.py`; 24 documentation files; 9 Alembic revisions; 181 release files вместе с manifest.
- Исходный Alembic head: `0009_candle_receipt_availability`.
- Исходный `SHA256SUMS`: PASSED, 180 checked files / 180 entries.
- `.env`, credentials, virtualenv, caches, dumps и реальные model artifacts во входном ZIP не обнаружены.
- Заявленные количества внешних ошибок не сопровождались modules, stack traces, datasets или reproductions. Severity присвоена только доказанному gap.

## Baseline до правок

Первый запуск в системном Python не считался валидным project baseline: отсутствовали проектные зависимости, а глобальный `pip check` содержал посторонние конфликты. Проверки повторены в изолированной `.venv`, созданной из `pyproject.toml`.

| Проверка | Статус | Результат |
|---|---|---|
| `.venv/bin/python --version` | PASSED | Python 3.13.5 |
| `.venv/bin/python -m pip check` | PASSED | no broken requirements |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `.venv/bin/python -m ruff check .` | PASSED | all checks passed |
| `.venv/bin/python -m pytest -q` | PASSED | **448 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `.venv/bin/python -m alembic heads` | PASSED | one head: `0009_candle_receipt_availability` |
| input release integrity | PASSED | 180 files checked / 180 manifest entries |
| `.venv/bin/python manage.py doctor` | FAILED / ENVIRONMENT | default secrets; `psql`, `pg_dump`, `pg_restore` and PostgreSQL server unavailable |
| `.venv/bin/python manage.py test --require-integration` | NOT RUN | no isolated PostgreSQL URL/server; production/user DB was not used |

Warnings are third-party NumPy/joblib deprecations in serialization tests.

## Подтверждённый gap

### HIGH — auto-activation игнорировал плотность исполнимой policy

`app/ml/training.py::evaluate_policy_model` уже рассчитывал `policy_candidates`, `policy_trades` и `policy_trade_rate`, но `app/ml/lifecycle.py::evaluate_quality_gate` проверял только абсолютное число trades/cohorts и point estimates economics.

До исправления candidate с 80 policy trades среди 100,000 evaluated symbol/timestamp candidates проходил gate при положительных средних метриках. Это позволяет автоматически продвинуть практически молчащую policy на основе микроскопической выбранной доли и создаёт operational/model-selection fragility.

Влияние: модель могла технически пройти promotion, но почти не формировать исполнимые рекомендации; небольшая выбранная подвыборка особенно чувствительна к случайности и выбору порогов. Gap не доказывает причину конкретных пользовательских убытков без runtime data.

Почему прежние тесты не поймали: quality-gate fixtures задавали trade count и cohorts, но не моделировали denominator/rate и не проверяли их арифметическую согласованность.

## Исправление

- Добавлен `AUTO_TRAIN_MIN_POLICY_TRADE_RATE=0.01` с обязательным диапазоном `(0, 1]`.
- Absolute gate теперь требует минимум 1% policy trades среди evaluated candidates в дополнение к raw-trade и independent-cohort minima.
- `policy_candidates`, `policy_trades` и `policy_trade_rate` проверяются на наличие, конечность, диапазон и равенство `trades / candidates`.
- Missing, malformed, contradictory или слишком разреженная evidence блокирует promotion fail-closed.
- Status diagnostics и quality-gate output показывают observed/minimum rate.
- Existing v10 policy metrics уже содержат эти поля; schema bump и migration не нужны.
- Live EV/RR/risk gates, advisory-only и PostgreSQL-only boundaries не ослаблены.

## Red → green

До production fix:

```text
FAILED test_quality_gate_rejects_statistically_sparse_policy
E assert True is False
1 failed in 3.13s
```

После fix:

```text
4 passed in 2.67s
```

Новый модуль также проверяет точную границу 1%, противоречивый ratio и invalid configuration.

## Post-check

| Проверка | Статус | Результат |
|---|---|---|
| `.venv/bin/python -m pip check` | PASSED | no broken requirements |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `.venv/bin/python -m ruff check .` | PASSED | all checks passed |
| `.venv/bin/python -m pytest -q` | PASSED | **452 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `.venv/bin/python -m alembic heads` | PASSED | one head: `0009_candle_receipt_availability` |
| `.venv/bin/python manage.py doctor` | FAILED / ENVIRONMENT | unchanged: default secrets, no PostgreSQL CLI/server |
| `.venv/bin/python manage.py test --require-integration` | NOT RUN | isolated PostgreSQL unavailable |
| Bybit order-mutation scan | PASSED | no create/amend/cancel/withdraw implementation in production paths |
| final release tree integrity | PASSED | 183 files checked / 183 manifest entries; ZIP test and clean re-extraction are performed after this report is sealed and stated in the release response |

## Не проверено и остаточные риски

- PostgreSQL transaction/advisory-lock paths and migration upgrade were not run on a real server; database schema was not changed.
- No live Bybit calls were made; deterministic tests were used.
- User database, candidate artifacts, trainer gate payloads, recommendation history, manual fills and realized outcomes were not supplied.
- The 1% threshold is an explicit operational guardrail, not a proof of an optimal trading frequency and not a profitability guarantee.
- Point estimates still need a separate uncertainty-aware work package (blocked/time-series bootstrap or equivalent) and forward/shadow evidence.
- Historical order-book/fill/funding parity, full walk-forward, drift/regime governance and PBO/DSR remain partial.
- One day of process uptime is not by itself training evidence. With defaults, the configured split/gates require at least 1206 unique hourly timestamps before candidate fit; progressive backfill may supply them, but exact gate failure requires runtime diagnostics.

## Version

- Result: `1.9.5` patch release.
- Migration: none; head remains `0009_candle_receipt_availability`.
- New dependency: none.
- New optional `.env` setting: `AUTO_TRAIN_MIN_POLICY_TRADE_RATE=0.01` (default applies when absent).
- Public API: additive status diagnostic only; no breaking contract change.
