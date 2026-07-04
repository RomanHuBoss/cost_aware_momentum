# QA Report — 1.9.4

Дата: 2026-07-04

## Входной архив

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `4e78746d3336f3611dab0dd4cf47ee70104fac868ed35f67b319c69de3f12a1e`.
- Исходная версия: `1.9.3`; Python requirement: `>=3.12`.
- Исходный состав: 85 production files в `app/`, `scripts/`, `web/`, `migrations/`; 54 `test_*.py` modules; 23 files в `docs/`; 9 Alembic revisions; 178 release files включая `SHA256SUMS`.
- Исходный Alembic head: `0009_candle_receipt_availability`.
- Исходный `SHA256SUMS` валиден: 177 release-файлов проверены и перечислены.
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
| `.venv/bin/python -m pytest -q` | PASSED | **444 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `.venv/bin/python -m alembic heads` | PASSED | one head: `0009_candle_receipt_availability` |
| input release integrity | PASSED | 177 files checked / 177 manifest entries |
| `.venv/bin/python manage.py doctor` | FAILED / ENVIRONMENT | default development secrets; `psql`, `pg_dump`, `pg_restore` and PostgreSQL server unavailable |
| `.venv/bin/python manage.py test --require-integration` | NOT RUN | no isolated PostgreSQL URL/server; production/user DB was not used |

Warnings are third-party NumPy/joblib deprecations in serialization tests.

## Подтверждённый дефект

### HIGH — partial hourly candle fetch блокировал сетевой retry до следующего часа

`sync_candles` правильно изолировал per-symbol Bybit exceptions и сохранял успешно полученные строки. Однако `hourly_market_close_job` возвращал только aggregate row count, а `run_job` фиксировал результат как `SUCCESS`. Повтор той же hourly job затем пропускался.

`hourly_inference` имел retry неполной публикации, но читал только PostgreSQL. Minute market sync обновлял tickers и загружал candle history лишь для newly admitted symbols. Поэтому transient timeout или payload без exact close оставлял `missing_decision_candle` без сетевого refetch до следующего часа.

Воспроизведение до исправления:

1. exact BTC candle получена, ETH kline timeout;
2. market-close job завершилась `SUCCESS`;
3. ETH inference blocked как `missing_decision_candle`;
4. дальнейшие inference retry не обращались к Bybit;
5. market-close retry отсутствовал.

Влияние: снижение полноты signal funnel при временных публичных API/сетевых сбоях. Fail-closed предотвращал ложный сигнал, поэтому дефект не доказывает причину конкретных убытков.

Почему прежние тесты не поймали: exact signal anchor и inference retry проверялись отдельно, без контракта per-symbol ingestion coverage → idempotent job retry.

## Исправление

- `sync_candles` получил опциональные exact-close diagnostics без изменения integer return contract.
- Coverage считается только по confirmed `last` candle с `close_time == required_close_time`; mark/index не могут закрыть обязательство.
- Диагностика сохраняет total/covered symbols, request counters, required timestamp и bounded sample отсутствующих symbols.
- Generic incomplete-success retry получил явные ключи total/covered/retry count; прежняя inference semantics сохранена wrapper-тестами.
- `hourly_market_close` повторяет public read-only fetch после cooldown, максимум пять раз, и прекращает retry при полном покрытии/нулевом universe/лимите.
- Exact-candle, ML quality, EV/RR, risk, execution, advisory-only и PostgreSQL gates не ослаблены.

## Red → green

До production fix:

```text
TypeError: sync_candles() got an unexpected keyword argument 'required_close_time'
KeyError: 'retry_incomplete_success'
2 failed in 2.87s
```

После production fix, вместе с existing inference-retry regressions:

```text
7 passed in 3.40s
```

## Post-check

| Проверка | Статус | Результат |
|---|---|---|
| `.venv/bin/python -m pip check` | PASSED | no broken requirements |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `.venv/bin/python -m ruff check .` | PASSED | all checks passed |
| `.venv/bin/python -m pytest -q` | PASSED | **448 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `.venv/bin/python -m alembic heads` | PASSED | one head: `0009_candle_receipt_availability` |
| `.venv/bin/python manage.py doctor` | FAILED / ENVIRONMENT | unchanged: development secrets, no PostgreSQL CLI/server |
| `.venv/bin/python manage.py test --require-integration` | NOT RUN | isolated PostgreSQL unavailable |
| Final release integrity / ZIP test | PASSED | 180 release files / 180 manifest entries; `unzip -t` and clean re-extraction passed |

## Не проверено и остаточные риски

- PostgreSQL transaction/advisory-lock path не запускался на реальном сервере; schema не менялась.
- Live Bybit timeout/rate-limit behavior не проверялось; использованы deterministic fakes.
- Не было пользовательской БД, job diagnostics, recommendations, candidate metrics, artifacts, fills и outcomes.
- Patch устраняет один доказанный источник пропуска сигналов, но не объясняет все `NO_TRADE` и не доказывает причину убытков.
- Одни сутки обучения не обеспечивают temporal depth/holdout и не гарантируют прохождение quality gates; thresholds не снижались.
- Historical order-book/fill/funding parity остаётся частичной; полный walk-forward, drift/regime governance, PBO/DSR и forward evidence не реализованы полностью.

## Version

- Result: `1.9.4` patch release.
- Migration: none; head `0009_candle_receipt_availability`.
- New environment variables/dependencies/public API changes: none.
