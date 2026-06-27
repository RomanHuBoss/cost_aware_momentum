# Iteration report — intrabar counterfactual outcomes

## 1. Входной архив и исходное состояние

- Входной архив: `cost_aware_momentum-main(4).zip`.
- SHA-256: `4653f12d4d99311a3303797535d541b696610e3118b9a677fdb08666c337bac7`.
- Исходная версия пакета / приложения: `1.6.0` / `1.6.0`.
- Python requirement: `>=3.12`.
- Alembic head: `0004_counterfactual_outcomes`.
- Исходный архив: 73 production/config/migration files, 13 test files, 12 documentation/source files по примененному inventory rule.
- Обнаруженный release-мусор: `cost_aware_momentum.egg-info/`; он исключен из новой поставки. Реальных `.env`, credentials, dumps или model artifacts не найдено.

## 2. Цель и критерии приемки

Цель: после этой итерации система должна разрешать порядок TP1/SL внутри неоднозначной hourly candle по точному complete 1/3/5-minute public/read-only path, оставляя outcome pending при неполных данных, что подтверждается regression tests, worker orchestration, diagnostics и полным static/unit post-check.

Критерии:

1. Неоднозначный hourly LONG и SHORT outcome разрешается по первому intrabar касанию.
2. Missing intrabar не превращается в TP, SL или TIMEOUT.
3. TP+SL внутри одного finest bar сохраняет conservative SL и `ambiguous=true`.
4. Worker запрашивает только exact symbol/hour windows, а не весь 5-minute universe.
5. Запрос использует только existing read-only `get_kline` и bounded `start/end/limit`.
6. Число windows на cycle ограничивается конфигурацией.
7. Existing immutable outcome/plan/audit/outbox semantics и advisory-only boundary не регрессируют.
8. Публичная API schema и PostgreSQL schema остаются обратно совместимыми.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `PATCH_1.3.0.md`–`PATCH_1.6.0.md`, `pyproject.toml`, `.env.example`, `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`, outcome/market-data/worker/config modules, unit/integration tests и приложенная DOCX-спецификация.

Спецификация прямо указывает: если TP и SL находятся внутри одной часовой свечи, основное решение — восстановить путь по 1–5-минутным свечам; резервное — неблагоприятное разрешение или исключение наблюдения.

Проверена официальная документация Bybit V5 `Get Kline` на 2026-06-28: `GET /v5/market/kline` поддерживает `start`, `end`, `limit` и интервалы `1`, `3`, `5` (`https://bybit-exchange.github.io/docs/v5/market/kline`).

Измененный поток:

```text
unresolved MarketSignal
→ contiguous confirmed hourly last-price path
→ detect first hourly candle with TP1+SL
→ exact public/read-only 1/3/5m symbol/hour fetch
→ PostgreSQL market.candles upsert
→ complete intrabar continuity validation
→ first TP1/SL hit or pending
→ immutable SignalOutcome
→ PlanOutcome(each version)
→ audit/outbox/API/UI
```

## 4. Baseline до правок

Первичный host environment не содержал Ruff и psycopg; этот запуск зафиксирован как environment failure, а не как дефект проекта. Затем declared dependencies были установлены в отдельный environment вне release tree.

| Команда | Статус и результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED после установки pip в isolated environment |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 67 passed, 3 skipped, 20 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | FAILED (environment): нет `.env`, PostgreSQL service/native tools и безопасных credentials |
| `python manage.py test --require-integration` | NOT RUN: нет отдельной PostgreSQL test database / admin URL |

## 5. Подтвержденный gap

### CONFIRMED GAP — hourly ambiguity не уточнялась finer-grained path

- Severity: medium, model/research correctness.
- Код: `app/services/outcomes.py::evaluate_barrier_outcome` и `resolve_counterfactual_outcomes`.
- Фактическое поведение 1.6.0: hourly `high >= TP` и `low <= SL` сразу давали `SL`, `ambiguous=true`.
- Отсутствующая функция: не было discovery точного ambiguous window, bounded 1/3/5-minute ingestion и continuity-aware intrabar evaluator.
- Влияние: TP-first сигнал мог быть записан как SL; counterfactual policy/calibration analysis получал консервативное систематическое искажение.
- Почему тесты не ловили: существующий test закреплял hourly conservative fallback, но не проверял основной intrabar путь из спецификации.

### DOCUMENTED LIMITATION — training labels остаются hourly

Эта итерация изменяет только post-event outcome journal. `app/ml/labels.py` и backtest не переводились на intrabar, чтобы не смешивать online journal с отдельным research work package.

## 6. План и фактический diff

Production:

- `app/services/outcomes.py`: intrabar-aware evaluator, ambiguous-window discovery, DB resolver integration, evaluation version `primary-barrier-intrabar-v2`.
- `app/services/market_data.py`: `CandleWindow` и exact bounded `sync_candle_windows` с per-window fail-closed diagnostics.
- `app/workers/runner.py`: discover → fetch → resolve orchestration в existing outcome job.
- `app/config.py`: interval и max-windows settings с validation.
- `app/__init__.py`, `pyproject.toml`: версия 1.7.0.

Tests:

- `tests/unit/test_intrabar_outcomes.py`: 7 acceptance/regression tests.

Config/docs:

- `.env.example`, `README.md`, `CHANGELOG.md`, `PATCH_1.7.0.md`.
- `docs/ARCHITECTURE.md`, `CONFIGURATION.md`, `INCIDENT_RUNBOOK.md`, `MODEL_CARD.md`, `OPERATOR_MANUAL.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`.
- текущий iteration report.

Migrations/API:

- migrations отсутствуют; head остается 0004;
- API fields не удалялись и не переименовывались;
- дополнительные details остаются внутри существующего JSONB contract.

## 7. Red → green evidence

Команда:

```text
python -m pytest -q tests/unit/test_intrabar_outcomes.py
```

RED до production implementation:

```text
ImportError: cannot import name 'CandleWindow' from 'app.services.market_data'
1 error during collection
```

GREEN после implementation:

```text
7 passed
```

Новые проверки независимо задают OHLC paths и ожидаемый первый barrier; тестируемая функция не используется как oracle.

## 8. Compatibility, config и rollback risks

- Версия: minor `1.7.0`, поскольку добавлена существенная обратно совместимая функция.
- DB migration: не требуется.
- Новые env variables имеют безопасные defaults: `5` минут и `100` windows/cycle.
- Existing 1.6.0 outcomes immutable и не пересчитываются.
- Новые ambiguous outcomes могут оставаться pending дольше вместо немедленного hourly SL; это намеренный fail-closed semantic change.
- API и frontend не требуют изменения: existing fields сохраняются, details расширены.

## 9. Post-check

| Команда | Статус и результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 74 passed, 3 skipped, 20 warnings |
| `python -m pytest -q tests/unit/test_intrabar_outcomes.py` | PASSED — 7 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0004_counterfactual_outcomes` |
| `python manage.py doctor` | FAILED (environment) — нет `.env`, PostgreSQL service/native tools и безопасных credentials |
| `python manage.py test --require-integration` | UNAVAILABLE — отдельная PostgreSQL test database не настроена |

Release recheck дополнительно включает whitespace scan, secret/artifact scan, отсутствие Bybit order methods, archive test и повторную распаковку.

## 10. Что не удалось проверить

- PostgreSQL integration/concurrency на реальном server;
- worker network smoke-test against live Bybit;
- rate-limit behavior при большом real backlog;
- Windows native runtime;
- API/UI display на живой локальной базе;
- экономическое влияние intrabar refinement на OOS metrics.

## 11. Остаточные риски и ограничения

- Training labels/backtest все еще используют hourly conservative ambiguity.
- Finer interval уменьшает, но не устраняет ambiguity: TP и SL могут быть внутри одного 1/3/5-minute bar.
- Bybit historical minute data/availability и API rate limits являются внешними ограничениями.
- Требуется полный intrabar hour; это намеренно консервативно и может задержать resolution при одном пропуске.
- TP2/partial exits/trailing stop, no-fill, operator latency и orderbook impact не моделируются.
- Counterfactual estimate не является actual manual trade P&L и не доказывает прибыльность.

## 12. Rollback procedure

1. Остановить worker/API.
2. Откатить code/config/docs к 1.6.0; database downgrade не нужен.
3. Удалить `OUTCOME_INTRABAR_*` из `.env` необязательно: 1.6.0 их игнорирует.
4. Перезапустить и проверить `python manage.py doctor`/readiness.
5. Уже сохраненные v2 outcomes не удалять и не редактировать; при строгой совместимости оставить 1.7.0 reader либо анализировать `evaluation_version` отдельно.

## 13. Следующий рекомендуемый work package

Перенести ту же intrabar path semantics в training label generation и barrier-policy backtest, добавив temporal comparison hourly-conservative vs intrabar-resolved labels. Не совмещать это с portfolio simulator, drift rollback или historical orderbook impact.

## Release note

Итоговый ZIP содержит этот report. Его окончательный SHA-256 сообщается рядом со ссылкой на архив: самовключение hash внутрь архива изменило бы hash файла. Внутренний `SHA256SUMS` фиксирует содержимое release tree и пересчитывается перед упаковкой.

## 14. Release validation

Финальный состав release tree перед упаковкой:

- 73 production-файла в `app/`, `scripts/`, `web/`, `migrations/`;
- 14 test-файлов;
- 13 файлов в `docs/`;
- 123 регулярных файла вместе с корневой документацией, конфигурацией и `SHA256SUMS`;
- один корневой каталог `cost_aware_momentum-1.7.0-intrabar-outcomes/`.

Проверки поставки:

- `SHA256SUMS` пересчитан по окончательному release tree и проходит `sha256sum -c`;
- `unzip -t` проходит без ошибок;
- архив повторно распакован в чистый каталог, внутренние checksums повторно проверены;
- `.env`, credentials, `.venv`, caches, `*.pyc`, `*.egg-info`, build/dist, dumps и реальные model artifacts отсутствуют;
- в production-коде не найдены Bybit order create/amend/cancel endpoints или методы.

SHA-256 самого ZIP сообщается внешне рядом со ссылкой на файл, поскольку включение его в содержимое архива изменило бы проверяемый hash.
