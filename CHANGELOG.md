# Changelog

## 1.4.0 — 2026-06-27

- Добавлен отдельный `trainer` process для фонового переобучения без блокировки API и inference worker.
- Trainer запускается вместе с `manage.py run`, имеет отдельные heartbeat, job history и команду `manage.py trainer`.
- Переобучение выполняется на rolling-окне подтвержденных часовых свечей после накопления минимального числа новых timestamps.
- Каждый цикл создает новый immutable joblib artifact; действующий файл модели не изменяется на месте.
- Candidate и incumbent сравниваются на одном новом final holdout по log loss, multiclass Brier и ECE.
- Добавлены абсолютные и относительные quality gates, минимальный размер holdout и контроль представленности TP/SL/TIMEOUT.
- Автоматическая activation выполняется только для прошедшего gate кандидата и только если active-version не изменилась во время обучения.
- При ошибке или провале gate текущая active-модель продолжает обслуживать inference; candidate остается неактивным для анализа.
- `ACTIVE_MODEL_PATH` блокирует auto-activation registry candidate, чтобы override не расходился со штатным runtime.
- Status/readiness показывают trainer heartbeat, фазу, последнюю попытку и конфигурацию auto-training.
- Ручные `train`, review, backtest, activation и rollback сохранены.

## 1.3.0 — 2026-06-27

- ML-задача заменена с бинарного направления на direction-specific `TP` / `SL` / `TIMEOUT`; `NO TRADE` остается решением policy engine.
- Добавлены pooled logistic baseline с feature×direction interactions и нелинейный HistGradientBoosting candidate.
- Реализованы отдельное temporal calibration window, sigmoid calibration и final holdout метрики Brier/log loss/ECE/AUC.
- Backtest переведен на barrier-policy outcomes и cost stress x1.5/x2; ограничения симулятора документированы явно.
- Legacy binary-direction artifacts отвергаются runtime.
- PostgreSQL model registry стал штатным источником active model: SHA/version/schema/classes/horizon проверяются worker.
- Добавлена явная activation/rollback CLI, audit/outbox event и уникальный индекс для одной active-модели.
- Worker периодически перечитывает registry и загружает модель без перезапуска; readiness сверяет registry/runtime/hash и свежесть market sync.
- Live inference использует point-in-time candle/spec cutoff и fail-closed блокировку при stale/missing обязательных данных.
- Production config запрещает baseline, demo seed и стандартные credentials.
- Добавлена честная матрица соответствия спецификации и перечень оставшихся исследовательских задач.

## 1.2.2 — 2026-06-27

- Для каждого символа в операторской панели остается только одна текущая рекомендация — самая свежая.
- При публикации нового часового сигнала предыдущий `PUBLISHED`-сигнал того же символа атомарно переводится в `SUPERSEDED`.
- Ожидающие исполнения планы старой рекомендации также получают статус `SUPERSEDED`; принятые и уже исполняемые планы сохраняются для торгового журнала.
- Добавлена частичная уникальность PostgreSQL: не более одного `PUBLISHED`-сигнала на символ.
- API и frontend получили дополнительную дедупликацию на время rolling upgrade.
- Устаревшую рекомендацию больше нельзя принять или пересчитать как актуальную.

## 1.2.1 — 2026-06-27

- Исправлена ошибочная трактовка Bybit `symbolType` как признака crypto/non-crypto.
- После стартового backfill и расширения universe выполняется catch-up inference для отсутствующих символов.
- API рекомендаций возвращает до 2000 карточек; UI явно запрашивает полный список.
- В системной строке показаны selected/eligible universe и число карточек.

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
