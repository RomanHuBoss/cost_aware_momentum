# Architecture

## Границы системы

Проект — локальная advisory-only система для Bybit linear USDT perpetuals. Он формирует market signals и account-dependent execution plans, но не размещает, не изменяет и не отменяет ордера.

## Процессы

1. **FastAPI/UI** — просмотр сигналов, планов, operator decisions и ручного журнала fills.
2. **Inference worker** — получение read-only market data, построение point-in-time features, runtime validation и публикация сигналов.
3. **Trainer** — отдельный процесс обучения, holdout/walk-forward evaluation, artifact registration и guarded promotion.
4. **PostgreSQL** — единственный state store; schema управляется Alembic.
5. **Research/maintenance CLI** — backtest, reports, backup/restore checks и release integrity.

## Ключевой data flow

Bybit/public+read-only state → point-in-time validation → features/model probabilities → capital-independent market policy → persisted `MarketSignal` → account/risk/liquidity validation → versioned `ExecutionPlan` → operator accept/reject → ручные fills/outcomes/audit.

## Инварианты

- PostgreSQL-only, без SQLite fallback и runtime `create_all`.
- Длительное обучение и ingestion не выполняются внутри HTTP request.
- Market signal не зависит от капитала; execution plan зависит.
- Ошибка данных, artifact, schema, риска или evidence блокирует действие.
- Model candidate immutable; activation требует quality и experiment gates.

## Clean-install training lifecycle

В dynamic mode trainer разделяет cold-start approximation и полное evidence:

1. `historical_frozen_dynamic_bootstrap` фиксирует последний свежий hash-validated execution cohort и использует historical data только внутри него.
2. `prospective_dynamic_replay` воспроизводит actual point-in-time membership/spread decisions по накопленным immutable snapshots.
3. Mode и evidence входят в artifact/quality-gate contract. При достаточной prospective depth trainer автоматически создаёт replacement candidate.

Exact replay не использует full-sample candle-coverage preselection. Bootstrap не реконструирует historical membership и не переиспользует stale snapshot.
