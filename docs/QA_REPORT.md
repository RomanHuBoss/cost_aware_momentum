# QA Report — 1.9.3

Дата: 2026-07-04

## Входной архив

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `bb815e0adc6f78853a3aad15441eb88ae3900cc073c275a620013de601045ce8`.
- Исходная версия: `1.9.2`; Python requirement: `>=3.12`.
- Исходный состав: 69 Python files в `app/` + `scripts/`, 53 `test_*.py` modules, 21 Markdown files в `docs/`, 9 Alembic revisions, 174 файла всего.
- Исходный Alembic head: `0009_candle_receipt_availability`.
- Исходный `SHA256SUMS` валиден: 173 release-файла проверены и перечислены.
- `.env`, credentials, virtualenv, caches, dumps и реальные model artifacts во входном ZIP не обнаружены.
- Заявленные внешними экспертами количества ошибок не сопровождались файлами, stack traces, данными или reproductions. Severity присвоена только воспроизведённому дефекту.

## Baseline до правок

Первый запуск в системном Python не являлся валидным project environment: отсутствовали `ruff` и `psycopg`, а глобальный `pip check` содержал посторонний конфликт MoviePy/Pillow. После штатного `python manage.py setup` baseline повторён в изолированной `.venv`.

| Проверка | Статус | Результат |
|---|---|---|
| `.venv/bin/python --version` | PASSED | Python 3.13.5; requirement выполнен |
| `.venv/bin/python -m pip check` | PASSED | no broken requirements |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `.venv/bin/python -m ruff check .` | PASSED | all checks passed |
| `.venv/bin/python -m pytest -q` | PASSED | **435 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `.venv/bin/python -m alembic heads` | PASSED | one head: `0009_candle_receipt_availability` |
| `python -B -m scripts.release_integrity --root .` | PASSED | 173 files checked / 173 manifest entries |
| `.venv/bin/python manage.py doctor` | FAILED / ENVIRONMENT | default development secrets; `psql`, `pg_dump`, `pg_restore` and PostgreSQL server unavailable |
| `.venv/bin/python manage.py test --require-integration` | NOT RUN | no isolated `POSTGRES_ADMIN_URL` or `TEST_DATABASE_URL`; production/user DB was not used |

Warnings are third-party NumPy/joblib deprecations in serialization tests.

## Подтверждённый дефект

### CRITICAL — capital profile обходил глобальный лимит совокупного риска

Конфигурация задавала:

- `MAX_TOTAL_OPEN_RISK_RATE=0.02`;
- `MAX_LEVERAGE=5`.

Но фактический путь имел независимые, более широкие профильные значения:

- `app/api/schemas.py` разрешал `max_total_risk_rate <= 0.20`;
- `app/api/v1/capital.py` сохранял payload без сверки с `Settings`;
- `app/services/execution.py` вычислял `capital * profile.max_total_risk_rate`;
- `app/api/v1/recommendations.py` повторно использовал тот же профильный лимит при acceptance;
- глобальные `default_risk_rate`/`max_total_open_risk_rate` были проверены при старте, но не являлись обязательной policy для профилей.

Воспроизведение при default settings:

1. legacy/profile `max_total_risk_rate=0.20`;
2. plan construction возвращал `ACTIONABLE`;
3. acceptance возвращал HTTP 200 и `ACCEPTED`.

Влияние: профиль мог увеличить совокупный риск до десятикратного значения относительно заявленного process-wide ceiling. Это прямой финансово-безопасностный дефект. Source-only reproduction не доказывает, что он вызвал конкретные исторические убытки пользователя.

Почему прежние тесты не поймали: отдельно тестировались корректность `Settings`, per-trade sizing, portfolio cap и fresh acceptance, но не было сквозного инварианта `profile ceiling <= runtime ceiling`.

## Исправление

- Добавлен единый контракт `app/risk/policy.py`:
  - `0 < risk_rate <= max_total_risk_rate <= MAX_TOTAL_OPEN_RISK_RATE`;
  - `1 <= default_leverage <= max_leverage <= MAX_LEVERAGE`;
  - конечный `margin_reserve_rate` в `[0, 1)`.
- Create-profile получает отсутствующие значения из runtime settings, а не из скрытых frontend/API констант.
- Create, patch и activate отклоняют небезопасный профиль HTTP 422 до mutation/recalculation.
- Plan construction проверяет persisted legacy row. Небезопасный профиль получает `BLOCKED_INVALID_INPUT`; safe runtime defaults используются только для неисполняемого diagnostic snapshot.
- Acceptance повторяет ту же проверку и требует новую версию плана вместо `ACCEPTED`.
- Portfolio API показывает effective global cap и блок `INVALID_CAPITAL_PROFILE_POLICY` для legacy row.
- Frontend перестал отправлять жёстко заданные `max_total_risk_rate=0.02` и `margin_reserve_rate=0.25`, показывает общий профильный лимит.
- Advisory-only, PostgreSQL-only, read-only Bybit и model lifecycle не изменены.

## Red → green

До production fix:

```text
2 failed
- expected BLOCKED_INVALID_INPUT, actual ACTIONABLE
- expected HTTP 409, actual HTTP 200
```

После production fix той же командой:

```text
2 passed in 1.27s
```

Дополнительно добавлены policy/default/patch/frontend regressions.

## Post-check

| Проверка | Статус | Результат |
|---|---|---|
| `.venv/bin/python -m pip check` | PASSED | no broken requirements |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `.venv/bin/python -m ruff check .` | PASSED | all checks passed |
| `.venv/bin/python -m pytest -q` | PASSED | **444 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `.venv/bin/python -m alembic heads` | PASSED | one head: `0009_candle_receipt_availability` |
| `.venv/bin/python manage.py doctor` | FAILED / ENVIRONMENT | unchanged environment limitations: development secrets, no PostgreSQL CLI/server |
| `.venv/bin/python manage.py test --require-integration` | NOT RUN | isolated PostgreSQL unavailable |
| Final release integrity / ZIP test | PASSED | 177 release files / 177 manifest entries; `unzip -t` and clean re-extraction passed |

## Не проверено и остаточные риски

- Не было пользовательской PostgreSQL-БД, job diagnostics, actual recommendations, candidate metrics, fills и outcomes. Причина редких сигналов и конкретных убытков не может быть доказана по source archive alone.
- PostgreSQL migrations/concurrency не запускались на реальном сервере; schema не менялась.
- Historical order-book/fill/funding parity в research остаётся частичной.
- Полный walk-forward, drift/regime governance, PBO/DSR и forward profitability evidence не реализованы полностью.
- Patch не ослабляет model-quality/policy gates и не обещает прибыльность.

## Version

- Result: `1.9.3` patch release.
- Migration: none; head `0009_candle_receipt_availability`.
- New environment variables: none.
