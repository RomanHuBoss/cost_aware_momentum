# Architecture

## Границы

Система advisory-only. Bybit client выполняет public/read-only GET operations; order placement, amend и cancel отсутствуют. PostgreSQL является единственным state store. API/UI, inference worker и trainer запускаются отдельными процессами.

## Training and validation data flow 1.13.0

1. Confirmed hourly last-price candles, hourly mark-price candles, фактические funding settlements и instrument funding interval загружаются из PostgreSQL одним `TrainingMarketData` bundle (`app/ml/lifecycle.py`).
2. `build_feature_frame()` строит point-in-time OHLCV features только из доступного прошлого last-price ряда. Future mark prices не входят в features.
3. `make_barrier_dataset()` формирует direction-specific `TP / SL / TIMEOUT` labels по last-price OHLC с execution spread proxy и привязывает funding aggregates к full horizon и actual modeled exit.
4. Для каждого label строится точная hourly mark-price timeline до modeled last-price exit. Gap, duplicate, неверная OHLC или несовпадение `open_time/close_time` исключают весь LONG/SHORT cohort fail-closed.
5. `simulate_intrahorizon_margin_path()` независимо восстанавливает directional mark-to-market, MAE/MFE, minimum equity и conservative isolated-margin liquidation proxy. Funding применяется по фактической границе settlement; выход на open не использует последующие экстремумы bar.
6. Future mark path не меняет target class, probabilities, direction ranking, RR, EV или actionability. Она может только сократить realized exit и заменить realized gross return/funding window после ex-ante выбора.
7. `chronological_split()` резервирует отдельный purged train/calibration/final-holdout split; final holdout используется один раз для candidate/incumbent и absolute gates.
8. Development region заканчивается до начала final holdout по `label_end_time`.
9. `expanding_walk_forward_splits()` строит три последовательных fold: expanding train, rolling calibration и более поздний неперекрывающийся test. Label overlap удаляется, вокруг границ применяется horizon embargo.
10. В каждом fold создаётся новый `TemporalCalibratedBarrierModel`; preprocessing fit выполняется только на fold train, calibration — только на fold calibration.
11. Fold-level ML/policy metrics, historical-funding evidence и intrahorizon-margin evidence сохраняются в immutable candidate artifact. Quality gate заново проверяет исходные records, временной порядок и арифметическую согласованность.
12. Runtime требует feature, label, temporal, walk-forward, funding и margin-path schemas. Candidate/incumbent comparison разрешён только при одинаковых entry/barrier, leverage и liquidation-reserve assumptions.

## Intrahorizon margin boundary

Реализация 1.13.0 является research-only conservative proxy:

- источник — hourly Bybit mark-price OHLC;
- initial margin rate — `1 / DEFAULT_LEVERAGE`;
- reserve — 10% initial margin;
- неблагоприятный mark return и фактически наступивший adverse funding уменьшают equity;
- favorable future funding не может предотвратить proxy liquidation;
- ambiguous same-bar liquidation считается раньше более позднего неупорядоченного last-price TP/SL;
- liquidation realized gross return равен полной initial margin rate со знаком минус.

Не реконструируются point-in-time risk tier/MMR, sub-hour order событий, liquidation fee, bankruptcy price, cross/portfolio margin, ADL, insurance-fund или fill mechanics. Поэтому модуль не должен называться точным Bybit liquidation engine.

## Неприкосновенные инварианты

- `NO TRADE` — policy decision, не market-model class.
- Features и ex-ante policy economics на decision time не используют future bars, future actual funding rates или future mark trajectory.
- Один timestamp/symbol и его LONG/SHORT pair не разрываются между окнами.
- Fold model и calibration не переиспользуются между временными окнами.
- Candidate не перезаписывает incumbent.
- Artifact hash/version/schema проверяются до inference.
- Stale/invalid/incompatible state блокируется fail-closed.
- Capital profile не меняет market direction или barrier geometry.
- Research leverage влияет на margin evidence, но не создаёт edge на notional и не меняет model probabilities.
