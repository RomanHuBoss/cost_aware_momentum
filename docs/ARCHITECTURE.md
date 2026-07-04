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

Account-dependent path: `capital-profile request/persisted row → global risk-policy validation → safe sizing → fresh acceptance revalidation → portfolio diagnostics`. Runtime settings are authoritative ceilings; invalid legacy rows fail closed and are never silently clamped into an actionable plan.

Для свечей `close_time` описывает рыночное время закрытия, а `available_at` всегда фиксирует локальное post-response receipt time. Поэтому поздний history/backfill не становится доступным replay задним числом. Legacy confirmed candles переякориваются migration 0009 к времени migration, поскольку точное исходное receipt time восстановить нельзя. Для остальных endpoint-данных без надёжного publish timestamp также используется локальное post-response receipt time. Inference применяет отдельно:

- `market_cutoff`: какие рыночные события относятся к решению;
- `available_cutoff`: какие данные были доступны к моменту вычисления.

Открытая свеча обновляется до первого confirmed snapshot. Confirmed snapshot не изменяется обычным upsert.

Hourly publication дополнительно связывает natural key и feature cutoff одним временным якорем: `frame.latest.close_time` обязан быть равен `signal.event_time`. Если API/ingestion ещё не принёс decision candle, worker возвращает fail-closed diagnostic `missing_decision_candle` и не запускает scenario economics. Это предотвращает раннюю публикацию на предыдущем часе и последующую блокировку корректного retry уже занятым natural key.


## Model artifact and promotion contract

`confirmed candles → contiguous features → first post-decision open entry proxy → direction-specific ATR-percentage labels → purged train/calibration/final holdout → train-only direction-conditional TIMEOUT return estimator → immutable candidate artifact → runtime schema/hash validation → same-task incumbent comparison → guarded activation`. The completed feature-candle close is not an executable research entry; the first bar open at `decision_time` is persisted as `entry_price`, and barrier distances use the same `atr_pct_14 × executable entry` geometry as live signal policy.

TIMEOUT returns are represented in stop-risk units (`realized_gross_return / barrier_downside_rate`). The artifact stores robust LONG/SHORT medians fit only on training TIMEOUT rows. Runtime scales the estimate to current tick-aligned stop distance; the selected gross value is persisted in the market signal and reused by plan/acceptance. Artifact validation is shared by production inference and research backtest. Candidate/incumbent comparison is allowed only when horizon, label/temporal/TIMEOUT semantics and ATR barrier multipliers match; otherwise promotion remains fail-closed and the incumbent stays active.


## Counterfactual outcome integrity

`signal.event_time → confirmed hourly/intrabar path → SignalOutcome` является market-level потоком. `ExecutionPlan` может использовать этот outcome для денежной оценки только при том же временном якоре. Если `plan.planning_time > signal.event_time`, точный путь после entry отсутствует, поэтому `PlanOutcome` записывается append-only со статусом `PATH_UNAVAILABLE`, нулевыми финансовыми полями и диагностикой. Migration 0008 также переводит ранее рассчитанные поздние планы в этот fail-closed статус.

Instrument specs для execution-проверок выбираются одновременно по `valid_from <= cutoff` и `received_at <= cutoff`; при одинаковом `valid_from` выбирается наиболее поздняя доступная к cutoff запись.

Policy equity/drawdown по-прежнему агрегируются по `exit_time`, но gross gain/loss для profit factor вычисляются из отдельных weighted trade contributions до взаимного неттинга. До расчёта research/promotion метрик actionable-кандидаты фильтруются по live-инварианту одного активного плана на symbol/account scope: кандидат с `decision_time < prior_exit_time` исключается, а вход на точной границе выхода разрешён. Схема метрик: `decision-open-entry-exit-time-cohort-v10`. Evidence v9 and earlier incompatible because it used one fixed TIMEOUT gross return instead of the artifact estimator.
