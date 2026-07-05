# Patch 1.10.0 — execution-entry alignment

## Проблема

Production signal policy использует ask для LONG и bid для SHORT, тогда как `make_barrier_dataset()` до версии 1.10.0 задавал обеим сторонам один `open` следующего часа. Это меняло entry, barrier geometry, outcome class и realized return в пользу недостижимого frictionless execution.

## Решение

- Добавлен full-spread stress `MODEL_ENTRY_SPREAD_BPS`.
- LONG/SHORT labels получают adverse half-spread вокруг historical hourly open proxy.
- Entry execution metadata записывается в dataset, metrics и immutable artifact.
- Runtime, quality gate и incumbent comparison отклоняют несовместимые semantics.
- Backtest реконструирует dataset с artifact-specific spread.

## Config

```env
MODEL_ENTRY_SPREAD_BPS=18
```

Это полный spread в basis points. Значение не моделирует depth, VWAP impact, no-fill, partial-fill или operator latency.

## Migration

Alembic migration отсутствует: схема PostgreSQL не менялась. После обновления необходимо переобучить model artifact; старые artifacts отклоняются fail-closed.

## Проверки

- Red: новый regression test завершался `TypeError`, потому что `make_barrier_dataset()` не принимал `entry_spread_bps`.
- Green: direction-specific entry tests проходят.
- Полный unit suite и static checks приведены в `docs/QA_REPORT.md`.

## Остаточные ограничения

Historical bid/ask/orderbook, exact funding timeline в research policy, rolling walk-forward, intrahorizon MTM/liquidation, PBO/DSR и drift monitoring остаются незакрытыми work packages.
