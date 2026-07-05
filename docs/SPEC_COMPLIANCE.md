# Specification Compliance

Состояние на 2026-07-05. Статусы основаны на фактическом коде release 1.14.0, а не на заявлении о полной реализации спецификации.

| Требование | Статус | Доказательство / ограничение |
|---|---|---|
| Advisory-only, read-only Bybit | Реализовано | `app/bybit/client.py` содержит GET market/account reads; order mutation methods отсутствуют. |
| PostgreSQL-only | Реализовано | SQLAlchemy/PostgreSQL models и Alembic; SQLite fallback отсутствует. |
| Point-in-time confirmed hourly data | Реализовано | `Candle.close_time`, `available_at`, confirmed semantics, temporal tests. |
| LONG/SHORT executable-side entry semantics | Частично реализовано 1.10.0 | Direction-specific adverse spread proxy. Exact historical bid/ask и operator latency отсутствуют. |
| Historical orderbook depth/VWAP/no-fill/partial-fill | Частично реализовано 1.14.0 | Forward point-in-time REST snapshots сохраняются в PostgreSQL; plan/acceptance используют direction-aware bounded-depth simulation, complete-fill VWAP и FULL/PARTIAL/NO_FILL evidence. Исторический backfill до 1.14.0, RPI/queue position, limit-order fill probability и реальный partial-fill lifecycle отсутствуют; поэтому model/backtest gap не считается закрытым. |
| Historical funding tied to actual settlements in research labels | Реализовано 1.12.0 для realized costs | Progressive backfill сохраняет фактические settlement timestamps; training/backtest агрегируют только события `(entry, actual_exit]` и fail-closed при гэпах. Будущая фактическая ставка не участвует в ex-ante selection. Исторические forecast snapshots и point-in-time изменения interval пока отсутствуют. |
| Rolling/expanding walk-forward | Реализовано 1.11.0 | Три purged expanding folds внутри development period, fresh fit/calibration на каждом fold и отдельный final holdout. Не является nested CV/PBO. |
| Operator-selection bias correction | Частично реализовано | Counterfactual outcome records существуют, causal/IPW/selection model отсутствует. |
| Intrahorizon MTM and liquidation simulation | Частично реализовано 1.13.0 | Training/backtest требуют exact hourly Bybit mark-price path, рассчитывают directional MAE/MFE/minimum equity и conservative isolated-margin liquidation proxy с actual funding timing; future mark path влияет только на realized evidence. Не реализованы sub-hour ordering, historical MMR/risk tiers, liquidation fees, cross/portfolio margin, ADL и точная exchange fill/liquidation mechanics. |
| OI/basis/funding/liquidity/context features | Не реализовано в model | Model использует 10 OHLCV-derived features; OI/funding могут храниться, но не входят в feature schema. |
| PBO, Deflated Sharpe, full experiment ledger | Частично реализовано | Immutable artifacts/model registry/backtest runs и fold evidence дают часть ledger; PBO/DSR отсутствуют. |
| Production drift monitoring | Не реализовано | Нет PSI/calibration/feature drift service и alert gate. |
