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

Trainer не модифицирует active artifact. Каждый цикл создает новую immutable-версию, сравнивает ее с incumbent на одном final holdout, сохраняет решение в `model_registry`, `job_runs`, audit и outbox. Автоматическая activation использует optimistic guard по предыдущей active-version, поэтому конкурентное изменение registry не может быть незаметно перезаписано.

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
- fail-closed при stale/missing data и migration mismatch; counterfactual outcome не создается при разрыве hourly path или неполном обязательном intrabar window;
- нативные `pg_dump`/`pg_restore` для резервирования и проверки восстановления.

## Security boundary

`BybitClient` предоставляет только public/read-only GET. Даже `ACCEPTED` означает решение оператора, а не биржевой ордер. Фактическое исполнение заносится через manual-entry/manual-close.
