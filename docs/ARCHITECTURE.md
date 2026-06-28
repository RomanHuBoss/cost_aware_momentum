# Архитектура

## Потоки

```text
Bybit public REST/WebSocket/read-only GET
        |
        v
market-data worker -> PostgreSQL market/reference
        |                         |
        |                         v
        |               background trainer -> immutable candidate -> quality gate
        |                                      |                         |
        |                                      v                         v
        |                              PostgreSQL model registry <- safe activation
        v
hourly feature snapshot -> ModelRuntime -> MarketSignal
        |
        v
cost/risk/policy + CapitalProfile + account/portfolio snapshot
        |
        v
ExecutionPlan(versioned) -> FastAPI -> Vanilla JS UI
        |
        v
operator accept/reject -> manual fill journal -> P&L/audit/reconciliation

confirmed hourly candles + MarketSignal
        |
        +-- same-hour TP/SL --> exact 1/3/5m read-only kline window
        |                              |
        v                              v
SignalOutcome -> PlanOutcome(each version) -> API/UI/audit/outbox
```

Market signal не зависит от профиля капитала. Execution plan зависит от профиля и snapshot счета. Один signal имеет несколько versioned plans.

## Нативные процессы

- `api`: HTTP/SSE, UI, validation и operator actions; запускается через `python manage.py api`.
- `worker`: ingestion, heartbeats, hourly inference, expiry и counterfactual outcome resolution с точечным intrabar backfill; запускается через `python manage.py worker`.
- `trainer`: периодическое переобучение, same-holdout comparison, quality gate и безопасная activation; запускается через `python manage.py trainer`.
- `migrate`: Alembic до первого запуска и после обновлений.
- `train/backtest`: ручные исследовательские CLI-процессы, не request-bound background tasks.
- PostgreSQL: отдельная системная служба и единый state store.

`python manage.py run` является локальным supervisor: запускает API, inference worker и, если `AUTO_TRAIN_ENABLED=true`, trainer как дочерние процессы, контролирует их завершение и останавливает все по `Ctrl+C`. Для постоянной эксплуатации процессы следует зарегистрировать как независимые службы ОС.

Trainer не модифицирует active artifact. Каждый цикл создает новую immutable-версию, сравнивает ее с incumbent на одном final holdout, сохраняет решение в `model_registry`, `job_runs`, audit и outbox. Начиная с 1.7.11 feature row допускается только при 24 последовательных одночасовых переходах, а label — только при наличии ровно следующих N часовых свечей; затронутые gaps/duplicates исключаются с diagnostics `hourly_continuity`. Начиная с 1.7.10 каждая barrier-label строка содержит фактический `label_end_time`; train и calibration допускаются только когда весь будущий label-window заканчивается до следующего окна, поэтому пропуски часовых свечей не сокращают purge. Номинальный horizon-hour embargo после границы сохраняется отдельно. Classification metrics используют зафиксированный artifact-порядок outcome classes; начиная с 1.7.9 `log_loss` вычисляется прямым выбором вероятности истинного класса и не зависит от внутренней сортировки labels библиотекой. Начиная с 1.7.8 новый gate-passed candidate регистрируется и активируется одной PostgreSQL-транзакцией: active-row блокируется, проверяется expected previous version, а candidate/activation audit и outbox фиксируются вместе. Автоматическая activation использует optimistic guard по предыдущей active-version, поэтому конкурентное изменение registry не может быть незаметно перезаписано. Если incumbent artifact физически утрачен и non-production baseline recovery явно разрешен, сравнение с недоступным файлом не имитируется: candidate проходит только абсолютные gates как при bootstrap и может заменить stale active row лишь после успешной проверки.

## Схемы PostgreSQL

- `reference`: инструменты и point-in-time contract specs.
- `market`: confirmed/unconfirmed candles, tickers, funding, OI.
- `research`: backtest runs и артефакты экспериментов.
- `model`: model registry, hashes и active version.
- `advisory`: profiles, signals, plans, signal/plan outcomes, decisions, fills и positions.
- `audit`: append-only chain и data-quality issues.
- `ops`: job runs, heartbeats, idempotency и outbox.

## Надежность

- natural unique keys и upsert ingestion;
- transaction-scoped advisory locks для коротких jobs и session advisory lock для длительного обучения;
- idempotency keys для operator mutations;
- transactional outbox для SSE/catch-up;
- Alembic head check до readiness;
- audit chain с сериализацией chain-head через PostgreSQL advisory lock;
- fail-closed при stale/missing/non-contiguous market data, migration mismatch и невалидном model artifact; физически отсутствующий active artifact имеет отдельный controlled baseline recovery только в non-production при явном разрешении; counterfactual signal outcome не создается при разрыве hourly path или неполном обязательном intrabar window; поврежденный execution-plan snapshot терминально сохраняется как zero-valued `INVALID_INPUT` и изолируется от других plan versions;
- нативные `pg_dump`/`pg_restore` для резервирования и проверки восстановления.

## Security boundary

`BybitClient` предоставляет только public/read-only GET. Даже `ACCEPTED` означает решение оператора, а не биржевой ордер. Фактическое исполнение заносится через manual-entry/manual-close.
