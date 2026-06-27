# Changelog

## 1.2.0 — 2026-06-27

- Добавлен динамический universe для всех активных Bybit linear USDT perpetuals.
- Полный каталог instruments-info загружается с пагинацией, затем сопоставляется с общим ticker snapshot.
- Добавлены фильтры статуса, типа контракта, pre-listing, возраста, 24h turnover, bid/ask spread, stablecoin-base и non-crypto symbol types.
- `UNIVERSE_MAX_SYMBOLS=0` включает все инструменты, прошедшие фильтры; статический режим сохранен.
- Новые участники universe автоматически получают backfill часовых свечей; перед каждым часовым inference обновляются свечи всего активного состава.
- Tickers сохраняются только для активного состава, добавлена управляемая retention-политика.
- Train/backtest в dynamic mode используют все накопленные символы, а не фиксированный список.
- Состав universe и причины исключения публикуются в worker heartbeat и job details.
- Добавлены регрессионные тесты выбора universe.

## 1.1.3 — 2026-06-27

- Fixed FastAPI and worker startup on Windows with async psycopg.
- Replaced Uvicorn-owned event-loop startup with an explicit SelectorEventLoop factory.
- Applied the same compatible runner to worker, training, backtest, reports and replay.
- Added regression tests for the explicit loop factory and runner.

## 1.1.2 — 2026-06-27

- Alembic переведен на синхронный psycopg migration runner, поэтому `manage.py migrate` больше не зависит от Windows event loop.
- Та же совместимость применяется к API, worker, train, backtest, replay и daily report.
- Добавлены регрессионные тесты настройки event loop.
- Docker по-прежнему не используется.

## 1.1.1 — 2026-06-27

- Исправлено чтение `SYMBOLS` и `HORIZONS_HOURS` из `.env` в формате списков через запятую.
- Добавлена совместимость с JSON-массивами для тех же параметров.
- Добавлены регрессионные тесты конфигурации Pydantic Settings.

## 1.1.0 — 2026-06-27

- Полностью удалена контейнерная конфигурация и связанные команды.
- Добавлен кроссплатформенный `manage.py` для установки, настройки, миграций, запуска, тестов и обслуживания.
- Добавлена нативная инициализация локальной PostgreSQL-роли и базы.
- Добавлен supervisor для одновременного запуска FastAPI и worker.
- Backup, restore-check и test runner переписаны на Python и используют системные PostgreSQL utilities.
- Добавлена диагностика окружения и отдельная инструкция для Windows, Linux и macOS.
- CI переведен на локальную PostgreSQL-службу, установленную системным пакетом.
- Обработчики завершения worker адаптированы для Windows.

## 1.0.0 — 2026-06-25

- FastAPI/PostgreSQL advisory backend and separate worker.
- Public/read-only Bybit V5 ingestion with no order endpoints.
- Capital-independent market signals and versioned profile-dependent execution plans.
- Cost-aware risk engine, portfolio/min-order/liquidity/margin guards.
- Russian operator UI with compact tiles, detailed modal and versioned glossary.
- Manual decision/fill lifecycle, idempotency, audit chain, outbox and reports.
- Training/backtest/replay CLI, tests, CI, backup and operational documentation.
