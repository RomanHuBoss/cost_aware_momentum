# Changelog

## 1.7.5 — 2026-06-28

- Position sizing now validates finite positive capital, risk rate, instrument steps/minima and leverage before any arithmetic.
- Non-finite margin/cap values and invalid margin reserve rates return zero-sized `BLOCKED_INVALID_INPUT` diagnostics instead of `decimal.InvalidOperation` or fail-open plans.
- Fee, slippage and stop-gap reserves must be finite and non-negative; signed finite funding remains supported.
- Invalid-input responses contain only finite capital/risk outputs, preventing `NaN`/`Infinity` from leaking into plan persistence or API serialization.
- Added red-to-green regression coverage for seven corrupted numeric-input classes while preserving all valid sizing results.

## 1.7.4 — 2026-06-28

- Risk mathematics now rejects inverted or non-finite LONG/SHORT entry, stop and take-profit geometry instead of converting it into a positive distance with `abs()`.
- Position sizing accepts the primary take-profit as part of its safety contract and returns `BLOCKED_INVALID_INPUT` with zero quantity/notional for invalid geometry.
- Execution-plan construction preserves the invalid-input block before policy classification and skips liquidation calculations that would otherwise operate on invalid prices.
- Manual fills whose actual entry is already beyond the directional stop boundary return HTTP 422 with a diagnostic instead of an unhandled server error.
- Counterfactual outcome evaluation and risk sizing now use one shared directional-geometry validator.
- Added regression tests proving fail-closed behavior for invalid LONG and SHORT barriers.

## 1.7.3 — 2026-06-28

- Trainer now treats an absent active artifact or an active deterministic baseline as an explicit bootstrap/recovery state before normal dataset-change scheduling.
- A missing usable ML model starts training after the normal startup delay without being blocked by an unrelated previous scheduled/data-change failure.
- Repeated technical bootstrap/recovery failures use `AUTO_TRAIN_RECOVERY_RETRY_MINUTES` (default 15) instead of the general six-hour retry window.
- A recovery candidate rejected by quality gates remains inactive and uses the controlled data-change cooldown, preventing a tight retraining loop on the same dataset.
- Added deterministic scheduler regression tests for missing artifacts, baseline bootstrap, unrelated prior failures and recovery backoff.

## 1.7.2 — 2026-06-28

- Worker больше не завершается при физическом отсутствии файла active-модели, если baseline явно разрешен и режим не production.
- Controlled fallback запускает `baseline-momentum-v1`, сохраняет stale registry row для аудита и публикует `ACTIVE_MODEL_ARTIFACT_MISSING` в heartbeat/status/UI.
- Отсутствие любой active registry row поддерживает bootstrap baseline до первой обученной модели.
- Worker работает со статусом `DEGRADED`, но readiness остается operational только для этого явно распознанного fallback без других ошибок и при свежих market data.
- Поврежденный artifact, SHA256/version/schema/classes/horizon mismatch и отсутствующий `ACTIVE_MODEL_PATH` остаются fail-closed.
- Trainer при утраченном incumbent использует recovery bootstrap: candidate проходит абсолютные ML/policy gates и может атомарно заменить stale active row; recovery context сохраняется в job, registry metrics и audit.
- Добавлены regression tests для worker startup, production boundary, strict override/integrity behavior и readiness.
- Migration и новые `.env` параметры не требуются.

## 1.7.1 — 2026-06-28

- Исправлен подтвержденный сбой регистрации model candidate в PostgreSQL JSONB при `incumbent_policy_realized_mean_r = -Infinity`.
- Quality-gate теперь отделяет внутренние fail-closed sentinel-значения от сериализуемого результата и сохраняет отсутствующие/non-finite метрики как JSON `null`.
- Добавлена рекурсивная нормализация JSON payload для model registry, trainer jobs/heartbeats, audit и outbox; `NaN`/`±Infinity` больше не попадают в JSONB.
- Сохранена прежняя логика абсолютных и incumbent-relative gate: исправление не ослабляет пороги и не активирует отклоненный кандидат.
- Добавлены regression tests для incumbent без policy-сделок, отсутствующих candidate policy metrics и вложенных NumPy/non-finite значений.
- Migration и новые `.env` параметры не требуются.

## 1.7.0 — 2026-06-28

- Добавлено автоматическое 1/3/5-минутное восстановление порядка TP1/SL для неоднозначных часовых свечей.
- Worker запрашивает только точные public/read-only kline windows, необходимые нерешенным сигналам, с лимитом на цикл.
- Outcome остается pending при неполном intrabar path; часовой консервативный SL больше не записывается до попытки реконструкции.
- Если TP и SL остаются внутри одного самого мелкого доступного бара, сохраняется консервативный SL с `ambiguous=true`.
- `SignalOutcome.details` фиксирует hourly ambiguity, фактический resolution interval и число проверенных intrabar bars.
- Добавлены настройки `OUTCOME_INTRABAR_INTERVAL` и `OUTCOME_INTRABAR_MAX_WINDOWS_PER_CYCLE`.
- Добавлены regression tests для LONG/SHORT, TP-first/SL-first, неполного пути, finest-bar ambiguity и bounded Bybit request.

## 1.6.0 — 2026-06-28

- Добавлен автоматический counterfactual outcome для каждого market signal независимо от accept/reject.
- Исход TP1/SL/TIMEOUT определяется по непрерывной последовательности confirmed hourly candles; пропуски оставляют outcome pending.
- Одновременное касание TP и SL внутри часа разрешается консервативно как SL с `ambiguous=true`.
- Для каждой execution-plan version сохраняются оценочные gross/net P&L и результат в R по immutable sizing/cost snapshot.
- Добавлены таблицы `advisory.signal_outcomes` и `advisory.plan_outcomes`, migration `0004_counterfactual_outcomes`.
- Outcome доступен в API detail, вкладке «Экономика», audit/outbox и hourly worker job.
- Добавлены regression tests для LONG/SHORT, ambiguity, missing bars, TIMEOUT, costs и unsized plans.

## 1.5.0 — 2026-06-28

- Добавлен dataset-aware trigger фонового переобучения: historical row growth, symbol coverage и universe change.
- Каждый model artifact хранит полный training-data profile и подписи состава/покрытия.
- Добавлен progressive history backfill до 365 дней без длительной блокировки старта.
- Auto-activation дополнена cost-aware holdout policy gates: trades, mean R, profit factor и drawdown.
- Главный экран фильтрует рекомендации по текущему universe и автоматически обновляет system status.
- Расширены `/api/v1/status`, `.env.example`, документация и regression tests.

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
