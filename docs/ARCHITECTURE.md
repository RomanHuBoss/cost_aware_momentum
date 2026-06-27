# Архитектура

## Потоки

```text
Bybit public REST/WebSocket/read-only GET
        |
        v
market-data worker -> PostgreSQL market/reference
        |
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
```

Market signal не зависит от профиля капитала. Execution plan зависит от профиля и snapshot счета. Один signal имеет несколько versioned plans.

## Нативные процессы

- `api`: HTTP/SSE, UI, validation и operator actions; запускается через `python manage.py api`.
- `worker`: ingestion, heartbeats, hourly inference и expiry; запускается через `python manage.py worker`.
- `migrate`: Alembic до первого запуска и после обновлений.
- `train/backtest`: отдельные CLI-процессы, не request-bound background tasks.
- PostgreSQL: отдельная системная служба и единый state store.

`python manage.py run` является локальным supervisor: запускает API и worker как дочерние процессы, контролирует их завершение и останавливает оба по `Ctrl+C`. Для постоянной эксплуатации процессы следует зарегистрировать как независимые службы ОС.

## Схемы PostgreSQL

- `reference`: инструменты и point-in-time contract specs.
- `market`: confirmed/unconfirmed candles, tickers, funding, OI.
- `research`: backtest runs и артефакты экспериментов.
- `model`: model registry, hashes и active version.
- `advisory`: profiles, signals, plans, decisions, fills и positions.
- `audit`: append-only chain и data-quality issues.
- `ops`: job runs, heartbeats, idempotency и outbox.

## Надежность

- natural unique keys и upsert ingestion;
- transaction-scoped advisory locks для jobs;
- idempotency keys для operator mutations;
- transactional outbox для SSE/catch-up;
- Alembic head check до readiness;
- audit chain с сериализацией chain-head через PostgreSQL advisory lock;
- fail-closed при stale/missing data и migration mismatch;
- нативные `pg_dump`/`pg_restore` для резервирования и проверки восстановления.

## Security boundary

`BybitClient` предоставляет только public/read-only GET. Даже `ACCEPTED` означает решение оператора, а не биржевой ордер. Фактическое исполнение заносится через manual-entry/manual-close.
