# Architecture

## Границы

Система advisory-only: она формирует market signals и account-dependent execution plans, но не создаёт, не изменяет и не отменяет биржевые ордера. PostgreSQL — единственный state store.

## Процессы

- FastAPI/API и локальный web UI.
- Inference/market-data worker.
- Отдельный trainer process.
- Research и maintenance CLI.

Длительные ingestion/training задачи не выполняются внутри HTTP request lifecycle.

## Point-in-time data flow

`Bybit read-only response → validation/normalization → event time + availability/receipt time → PostgreSQL → feature/inference cutoff → signal → execution plan → UI`.

Для свечей `close_time` описывает рыночное время закрытия. `available_at` отражает предусмотренный source-availability момент подтверждённой свечи. Для endpoint-данных без надёжного publish timestamp используется локальное post-response receipt time. Inference применяет отдельно:

- `market_cutoff`: какие рыночные события относятся к решению;
- `available_cutoff`: какие данные были доступны к моменту вычисления.

Открытая свеча обновляется до первого confirmed snapshot. Confirmed snapshot не изменяется обычным upsert.


## Model artifact and promotion contract

`confirmed candles → contiguous features → direction-specific ATR labels → purged train/calibration/final holdout → immutable candidate artifact → runtime schema/hash validation → same-task incumbent comparison → guarded activation`.

Artifact validation is shared by production inference and research backtest. Candidate/incumbent comparison is allowed only when horizon, label/temporal semantics and ATR barrier multipliers match; otherwise promotion remains fail-closed and the incumbent stays active.


## Counterfactual outcome integrity

`signal.event_time → confirmed hourly/intrabar path → SignalOutcome` является market-level потоком. `ExecutionPlan` может использовать этот outcome для денежной оценки только при том же временном якоре. Если `plan.planning_time > signal.event_time`, точный путь после entry отсутствует, поэтому `PlanOutcome` записывается append-only со статусом `PATH_UNAVAILABLE`, нулевыми финансовыми полями и диагностикой. Migration 0008 также переводит ранее рассчитанные поздние планы в этот fail-closed статус.

Instrument specs для execution-проверок выбираются одновременно по `valid_from <= cutoff` и `received_at <= cutoff`; при одинаковом `valid_from` выбирается наиболее поздняя доступная к cutoff запись.

Policy equity/drawdown по-прежнему агрегируются по `exit_time`, но gross gain/loss для profit factor вычисляются из отдельных weighted trade contributions до взаимного неттинга. Схема метрик: `exit-time-open-gap-propagated-cohort-weighted-v6`.
