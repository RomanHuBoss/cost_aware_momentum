# QA report

Дата проверки версии 1.7.2: 28 июня 2026 г.

## Итерация 1.7.2 — recovery после удаления active model artifact

Подтвержден пользовательский startup failure: registry-active модель оставалась в PostgreSQL, но удаленный `.joblib` приводил к завершению inference worker до heartbeat. Исправление добавляет controlled baseline fallback и bootstrap recovery trainer без ослабления production/integrity boundary.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `75740b1e1a908e4a7040ee5bbaa6f9d8b2876e253d5e5eaa3d82b3d2c158788b` |
| Baseline `python -m pytest -q` | PASSED — 77 passed, 3 skipped |
| Red regression test | PASSED как доказательство gap — collection failed: `ModuleNotFoundError: app.ml.runtime_selection` |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 88 passed, 3 skipped |
| model fallback targeted tests | PASSED — 11 passed |
| `node --check web/js/app.js` | PASSED |
| PostgreSQL integration | NOT RUN — отдельная test database отсутствует |
| Migration | не требуется; head остается `0004_counterfactual_outcomes` |

`python -m pip check` в host environment остается FAILED из-за внешнего конфликта `moviepy 2.2.1`/`pillow 12.2.0`, не объявленного данным проектом. Missing artifact recovery проверен unit-level через фактический `Worker.refresh_model_runtime()` с mock PostgreSQL session; SQLite/fake application database не применялась.

Полный отчет: `docs/ITERATION_REPORT_2026-06-28-model-artifact-recovery.md`.

## Историческая проверка версии 1.7.1

## Итерация 1.7.1 — JSON-safe model lifecycle

Подтвержден пользовательский PostgreSQL failure при регистрации candidate: JSONB отвергал `-Infinity` в `quality_gate.relative.incumbent_policy_realized_mean_r`. Исправление отделяет внутренние fail-closed sentinels от сериализуемых значений и нормализует model/trainer/audit JSON payload.

| Проверка | Результат |
|---|---|
| Input ZIP SHA-256 | `58e1270f61c0d6efc8e731790e8a5cbe673278d021fe61e7b2d3db9bd80732b6` |
| Red regression tests | PASSED как доказательство дефекта — 2 tests failed с strict-JSON `-inf` |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 77 passed, 3 skipped |
| lifecycle/json targeted tests | PASSED — 7 passed |
| `node --check web/js/app.js` | PASSED |
| PostgreSQL integration | NOT RUN — отдельная test database отсутствует |
| Migration | не требуется; head остается `0004_counterfactual_outcomes` |

`python -m pip check` в host environment остается FAILED из-за внешнего конфликта `moviepy 2.2.1`/`pillow 12.2.0`, не объявленного данным проектом. Полный отчет: `docs/ITERATION_REPORT_2026-06-28-model-registry-json-safety.md`.

## Историческая проверка версии 1.7.0

## Baseline до изменений

Входной архив: `cost_aware_momentum-main(4).zip`, SHA-256 `4653f12d4d99311a3303797535d541b696610e3118b9a677fdb08666c337bac7`.

Проверки исходной версии 1.6.0 выполнены в изолированном Python environment после установки declared dependencies:

| Проверка | Результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — broken requirements не обнаружены |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 67 passed, 3 skipped, 20 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | FAILED (environment) — нет `.env`, native PostgreSQL tools/service и безопасных credentials |
| `python manage.py test --require-integration` | NOT RUN — отсутствуют `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` и отдельная PostgreSQL test database |

Первый запуск в host environment без declared dev/runtime dependencies был также зафиксирован: Ruff и psycopg отсутствовали, поэтому он не использовался как доказательство качества проекта.

## Post-check версии 1.7.0

| Проверка | Результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 74 passed, 3 skipped, 20 warnings |
| `python -m pytest -q tests/unit/test_intrabar_outcomes.py` | PASSED — 7 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — единственный head `0004_counterfactual_outcomes` |
| Версия пакета / приложения | `1.7.0` / `1.7.0` |
| `python manage.py doctor` | FAILED (environment) — нет `.env`, замененных secrets, PostgreSQL service и `psql`/`pg_dump`/`pg_restore` |
| `python manage.py test --require-integration` | UNAVAILABLE — отдельная PostgreSQL test database не настроена |

3 skipped tests являются PostgreSQL integration tests и не заменены SQLite/fake database.

## Red → green evidence

До production implementation создан и запущен новый module:

```text
python -m pytest -q tests/unit/test_intrabar_outcomes.py
```

RED: collection завершилась `ImportError: cannot import name 'CandleWindow' from 'app.services.market_data'`.

GREEN: тот же module прошел — `7 passed`.

## Проверенный контракт intrabar outcome

Unit tests и static analysis подтверждают:

1. hourly non-ambiguous TP/SL/TIMEOUT behavior сохранено;
2. LONG и SHORT используют правильную directional geometry;
3. hourly TP+SL разрешается по первому касанию в complete 1/3/5-minute path;
4. source candle и exit time получают intrabar precision;
5. missing intermediate intrabar оставляет outcome pending;
6. TP+SL внутри одного finest bar дает conservative SL и `ambiguous=true`;
7. точечный fetch использует только public/read-only kline window с exact `start`, `end`, `interval`, `limit`;
8. запросы дедуплицируются по symbol/start/end и ограничиваются конфигурацией;
9. fetch error не создает выдуманный outcome;
10. existing immutable outcome, plan valuation, audit/outbox и advisory-only границы не изменены.

## Проверка внешнего контракта Bybit

28 июня 2026 г. проверена официальная документация Bybit V5 `Get Kline`: endpoint является `GET /v5/market/kline`, принимает `start`, `end`, `limit` и интервалы `1`, `3`, `5` среди поддерживаемых. Production tests используют mock/fake client и не выполняют торговых операций.

## PostgreSQL integration tests

В среде сборки отсутствовали PostgreSQL server/native utilities и отдельная test database. Миграция не менялась, но DB flow с existing `market.candles` и `advisory.signal_outcomes` не проверялся фактической concurrent integration с PostgreSQL.

Перед эксплуатацией выполнить:

```powershell
$env:POSTGRES_ADMIN_URL="postgresql+psycopg://postgres:ПАРОЛЬ@localhost:5432/postgres"
py -3.12 manage.py test --require-integration
Remove-Item Env:POSTGRES_ADMIN_URL
```

Дополнительно проверить worker smoke-test на paper/shadow:

1. hourly bar с TP1+SL;
2. загрузку 12 пяти-минутных candles для одного часа;
3. pending при неполном path;
4. повторный cycle после восстановления API;
5. audit/outbox/API detail для intrabar-resolved outcome.

## Release boundary

Проверяется перед упаковкой:

- Bybit client содержит только GET/public/read-only methods;
- PostgreSQL-only и advisory-only границы сохранены;
- release исключает `.env`, credentials, `.venv`, caches, `*.egg-info`, dumps и real model artifacts;
- `SHA256SUMS` пересчитывается после финального состава release.

## Не покрыто данной проверкой

- фактический PostgreSQL integration/concurrency run;
- длительный worker smoke-test на реальном потоке Bybit;
- intrabar reconstruction в training labels и backtest;
- TP2/partial exits, no-fill, operator latency и historical orderbook impact;
- comparison counterfactual estimate с manual fills;
- paper/shadow forward evidence и экономическое преимущество стратегии.

Финальные release hash и повторная распаковка фиксируются в `docs/ITERATION_REPORT_2026-06-28_intrabar-outcomes.md`.
