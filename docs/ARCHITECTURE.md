# Architecture

## Границы

Система advisory-only. Bybit client выполняет public/read-only GET operations; order placement, amend и cancel отсутствуют. PostgreSQL является единственным state store. API/UI, inference worker и trainer запускаются отдельными процессами.

## Training and validation data flow 1.12.0

1. Confirmed hourly last-price candles, фактические funding settlements и instrument funding interval загружаются из PostgreSQL одним `TrainingMarketData` bundle (`app/ml/lifecycle.py`).
2. `build_feature_frame()` строит point-in-time OHLCV features только из доступного прошлого.
3. `make_barrier_dataset()` формирует direction-specific `TP / SL / TIMEOUT` labels с execution spread proxy и привязывает funding aggregates к full horizon и actual modeled exit.
4. `chronological_split()` резервирует отдельный purged train/calibration/final-holdout split; final holdout используется один раз для candidate/incumbent и absolute gates.
5. Development region заканчивается до начала final holdout по `label_end_time`.
6. `expanding_walk_forward_splits()` строит три последовательных fold: expanding train, rolling calibration и более поздний неперекрывающийся test. Границы проходят по целым decision timestamps; label overlap удаляется, вокруг границ применяется horizon embargo.
7. В каждом fold создаётся новый `TemporalCalibratedBarrierModel`, preprocessing fit выполняется только на fold train, calibration — только на fold calibration.
8. Fold-level ML и policy metrics агрегируются, но quality gate заново проверяет исходные fold records, их порядок, арифметическую согласованность и временное неперекрытие.
9. Candidate artifact сохраняет temporal и walk-forward schemas; runtime отклоняет несовместимые artifacts fail-closed.
10. Final holdout остаётся отдельным от walk-forward и используется для совместимого сравнения candidate с incumbent.
11. В policy evaluation будущие actual funding rates исключены из direction/actionability/EV; только события до actual exit входят в realized PnL.
12. Artifact сохраняет funding timeline evidence; runtime и activation gate отклоняют отсутствующую/несовместимую schema.

## Неприкосновенные инварианты

- `NO TRADE` — policy decision, не market-model class.
- Features и ex-ante policy economics на decision time не используют future bars или future actual funding rates.
- Один timestamp/symbol и его LONG/SHORT pair не разрываются между окнами.
- Fold model и calibration не переиспользуются между временными окнами.
- Candidate не перезаписывает incumbent.
- Artifact hash/version/schema проверяются до inference.
- Stale/invalid/incompatible state блокируется fail-closed.
- Capital profile не меняет market direction или barrier geometry.
