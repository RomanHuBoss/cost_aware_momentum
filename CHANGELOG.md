# Changelog

## 1.13.0 — 2026-07-05

### Added

- Progressive read-only backfill of hourly Bybit mark-price candles using the existing candle table and explicit `price_type=mark`.
- Realized-only intrahorizon mark-to-market replay with directional MAE/MFE, minimum equity and conservative isolated-margin liquidation evidence.
- Exact hourly mark-timeline completeness checks and immutable `intrahorizon_margin_schema=bybit-mark-price-hourly-isolated-margin-proxy-v1`.
- Nine regression tests covering LONG/SHORT MTM, same-bar liquidation precedence, exit-at-open, funding timing, missing mark bars, look-ahead isolation and backfill typing.

### Changed

- Training and backtest now require a complete hourly mark-price path through each modeled last-price exit.
- Future mark prices can only rewrite realized exit/PnL evidence; direction, RR, EV and actionability remain ex-ante and unchanged.
- Candidate/incumbent comparison and runtime validation require compatible leverage and liquidation-reserve assumptions.
- Policy metric schema is `decision-open-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v15`.

### Compatibility

- No database migration and no new `.env` variable. `DEFAULT_LEVERAGE` becomes part of the research artifact contract.
- Artifact 1.12.0 lacks the mandatory intrahorizon margin contract and must be retrained after mark-price history reaches complete coverage.
- The implementation is a conservative hourly isolated-margin proxy, not an exact Bybit liquidation engine.

## 1.12.0 — 2026-07-05

### Added

- Progressive read-only backfill of actual Bybit funding settlement events using bounded `endTime` pagination and the existing PostgreSQL funding table.
- Event-time historical funding replay over `(entry_time, exit_time]`, with completeness checks against the configured instrument settlement interval.
- Funding timeline metadata and `historical_funding_schema=bybit-settlement-timestamp-replay-v1` in candidate artifacts and runtime validation.
- Seven regression tests for settlement boundaries, missing events, LONG/SHORT signs, request bounds and future-funding leakage.

### Changed

- Training and backtest load candles, funding history and instrument funding intervals as one research-data bundle.
- Realized OOS policy/backtest PnL includes only funding settlements actually crossed before the modeled exit.
- Actual future funding rates are excluded from ex-ante direction selection, RR, EV and actionability; the explicit backtest funding override remains an adverse stress only.
- Policy metric schema is `decision-open-directional-spread-entry-funding-timeline-exit-time-cohort-v14`.

### Compatibility

- No database migration and no new `.env` variable.
- Artifact 1.11.0 lacks the mandatory historical-funding contract and must be retrained after funding history reaches the required coverage.

## 1.11.0 — 2026-07-05

### Добавлено

- Трёхфолдовый expanding walk-forward внутри development period с целыми decision timestamps, label-end purge и horizon embargo.
- Независимое переобучение и sigmoid calibration модели в каждом fold; final holdout не используется в walk-forward оценке.
- Fold-level evidence в immutable artifact: временные границы, row counts, log loss, prior skill, multiclass Brier и policy metrics.
- Fail-closed auto-activation gates для количества/порядка folds, временного перекрытия, худшего fold и устойчивости положительного ML skill и policy mean R.

### Изменено

- Temporal schema обновлена до `final-holdout-plus-expanding-walk-forward-v4`.
- Runtime требует `walk_forward_schema=expanding-train-rolling-calibration-purged-v1`.
- Минимальный объём истории теперь рассчитывается с учётом purged walk-forward windows; при текущих defaults требование остаётся 1206 hourly timestamps.

### Совместимость

- Миграция БД и новые `.env` переменные не требуются.
- Artifact 1.10.0 не содержит обязательную walk-forward schema и должен быть переобучен.
- Реализация не является PBO, nested cross-validation или доказательством прибыльности.

## 1.10.0 — 2026-07-05

### Исправлено

- Historical barrier labels больше не используют один frictionless `next-hour open` одновременно для LONG и SHORT. Entry proxy теперь direction-specific: LONG = open + half-spread, SHORT = open - half-spread.
- Первый label bar нормализуется к моменту моделируемого входа, чтобы движение до adverse spread entry не интерпретировалось как исполнимый TP/SL.
- Training, automatic trainer и research backtest используют единый `MODEL_ENTRY_SPREAD_BPS`.
- Artifact runtime и auto-activation gate fail-closed проверяют execution schema и spread value.
- Candidate/incumbent comparison пропускается при несовместимых entry spread/barrier semantics.

### Добавлено

- Конфигурация `MODEL_ENTRY_SPREAD_BPS` с default `18` bps.
- Regression tests для direction-specific entry, invalid configuration, artifact compatibility и quality-gate consistency.
- Документы архитектуры, конфигурации, QA, compliance, traceability, model card, security, runbook и operator manual, отсутствовавшие во входном release tree.

### Совместимость

- Миграция БД не требуется.
- Model artifacts с прежней label/execution schema несовместимы и должны быть переобучены.
