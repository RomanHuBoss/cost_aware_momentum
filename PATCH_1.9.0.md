# Patch 1.9.0 — conditional TIMEOUT economics

Дата: 2026-07-02

## Проблема

До 1.9.0 ML policy, live signal, execution plan и research backtest присваивали любому исходу `TIMEOUT` один gross return `TIMEOUT_GROSS_RETURN_RATE=-0.002`. Dataset при этом уже содержал фактическую direction-signed TIMEOUT return и contemporaneous stop distance. Глобальная константа смешивала LONG/SHORT и положительные/отрицательные TIMEOUT paths, искажая EV, direction ranking и promotion evidence.

## Решение

- Trainer строит train-only target `realized_gross_return / barrier_downside_rate` для TIMEOUT rows.
- Для LONG и SHORT сохраняется отдельная медиана; требуется минимум 5 train TIMEOUT rows на направление.
- Runtime переносит estimate в directional prediction.
- Live policy, promotion evaluation и research backtest масштабируют estimate к текущей stop geometry и ограничивают его текущей TP/SL support.
- Signal snapshot сохраняет `timeout_gross_return_rate`, `timeout_return_r` и source.
- Execution plan/acceptance повторно используют persisted signal assumption и отклоняют NaN/infinity.
- Новый artifact contract: `timeout_return_schema_version=training-direction-median-r-v1`.
- Новый policy evidence contract: `decision-open-entry-exit-time-cohort-v10`.

## Совместимость

- Alembic migration отсутствует.
- Новых `.env`-переменных нет.
- `TIMEOUT_GROSS_RETURN_RATE` остаётся baseline/legacy fallback.
- Старые artifacts без нового schema блокируются fail-closed; требуется штатное переобучение.
- Existing signals сохраняют исходную persisted assumption; новая логика не переписывает историю.

## Проверки

- Baseline: 425 passed, 4 skipped.
- Red: новый regression module не собирался, потому что conditional TIMEOUT contract отсутствовал.
- Green: новый module — 7 passed.
- Full suite: 432 passed, 4 skipped.
- Ruff, compileall, pip check, Node syntax and Alembic single-head checks passed.
- PostgreSQL integration and `manage.py doctor` not run because no isolated test DB/operator configuration was available.

## Ограничения

Direction-specific train median является минимальным устойчивым estimator, а не полноценной feature-conditional regression. Его пригодность должна подтверждаться paper/shadow forward evidence. Historical order book/fill/funding replay и full rolling walk-forward не реализованы этой итерацией.

Отдельно подтверждён, но не исправлен в этом scope, дефект candle availability: late-fetched candles получают `available_at=close_time`, а не фактический receipt time. Требуется отдельная migration/reingestion policy.
