# Architecture

## Границы

Система advisory-only. Bybit client выполняет public/read-only GET operations; order placement, amend и cancel отсутствуют. PostgreSQL является единственным state store. API/UI, inference worker и trainer запускаются отдельными процессами.

## Изменяемый data flow 1.10.0

1. Confirmed hourly last-price candles загружаются из PostgreSQL (`app/ml/lifecycle.py`).
2. `build_feature_frame()` строит point-in-time OHLCV features.
3. `make_barrier_dataset()` начинает label horizon после decision candle close.
4. Первый future hourly open используется только как mid proxy. `MODEL_ENTRY_SPREAD_BPS / 2` добавляется LONG и вычитается SHORT.
5. Direction-specific entry определяет TP/SL geometry, class label и realized gross return.
6. Purged chronological train/calibration/final-holdout split обучает и оценивает candidate.
7. Execution metadata входит в metrics и immutable artifact.
8. Quality gate сверяет metadata с текущей конфигурацией; runtime повторно валидирует artifact.
9. Research backtest использует spread, записанный в artifact.

## Неприкосновенные инварианты

- `NO TRADE` — policy decision, не market-model class.
- Features на decision time не используют future bars.
- Candidate не перезаписывает incumbent.
- Artifact hash/version/schema проверяются до inference.
- Stale/invalid/incompatible state блокируется fail-closed.
- Capital profile не меняет market direction или barrier geometry.
