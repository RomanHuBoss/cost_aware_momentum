# Changelog

## 1.19.0 — 2026-07-05

- Добавлен единый dependence-aware research layer: Bartlett/Newey–West HAC для среднего и детерминированный moving-block bootstrap для среднего return и non-annualized Sharpe.
- Deflated Sharpe в experiment-family report использует HAC-implied effective observation count вместо номинального числа зависимых почасовых строк.
- Block length experiment report автоматически не может быть короче заявленного trading horizon; слишком малое число независимых блоков даёт `BLOCKED_INSUFFICIENT_DEPENDENCE_EVIDENCE`.
- Статус `READY` теперь дополнительно требует положительных нижних confidence bounds HAC mean, block-bootstrap mean и block-bootstrap Sharpe; это research governance, а не auto-activation.
- Chronological propensity scoring больше не разделяет plan versions одного signal между training и OOS block; перекрывающиеся signal windows исключаются из training cutoff.
- Operator-selection report использует signal-cluster moving-block bootstrap для интервалов all-eligible, selected-only, IPSW mean и selected-subset bias; недостаток независимых signal clusters блокирует corrected result.
- Добавлены шесть fail-closed `RESEARCH_*`/dependence settings, девять regression tests и синхронизированная эксплуатационная документация.
- Миграция БД и переобучение market model не требуются; advisory-only и `automatic_model_action=none` сохранены.

## 1.18.0 — 2026-07-05

- Добавлен append-only `research.experiment_events` ledger: каждая валидированная research backtest-оценка записывает `STARTED` и терминальное `SUCCEEDED/FAILED` событие с неизменяемой конфигурацией, canonical SHA-256 и hash chain.
- Успешные trials сохраняют выровненный почасовой return path, включая нулевые часы, а не только агрегированный Sharpe или итоговый capital.
- Добавлен contiguous CSCV/PBO по всем уникальным успешно раскрытым конфигурациям одной experiment family.
- Добавлен Deflated Sharpe Ratio с поправкой на skewness/kurtosis, variance Sharpe across trials и correlation-implied effective number of independent trials.
- Неполные/failed/open attempts, недостаток trials/periods, несопоставимые timestamps, redundant evidence или повреждённая hash chain блокируют отчёт fail-closed.
- Повторные запуски одинаковой конфигурации дедуплицируются при выборе вариантов и отдельно раскрываются как repeated attempts.
- Добавлены `manage.py experiment-report`, `cam-experiment-report`, настройки `EXPERIMENT_*`, migration `0012_experiment_selection` и десять regression tests.
- Governance остаётся research-only: `automatic_model_action=none`, `profitability_claimed=false`; active model, live policy и risk limits не изменяются.

## 1.17.0 — 2026-07-05

- Добавлен immutable final-holdout drift reference для всех 17 ex-ante base features, обеих directional probability distributions, selected-direction calibration и policy actionability density.
- Hourly production monitor рассчитывает inference coverage, feature missingness, feature/probability PSI, selected-direction log-loss/Brier deltas и actionability-rate drift только для активной model version.
- Reference использует фиксированные holdout quantile bins; production не переоценивает границы по текущему окну и не смешивает версии модели.
- Failed inference jobs, некорректный coverage accounting, недостаток наблюдений или несовместимый artifact дают `BLOCKED`; критический drift переводит worker heartbeat в `DEGRADED`.
- Монитор не активирует, не деактивирует и не откатывает модели и не ослабляет ML/policy/risk gates; `automatic_model_action=none` фиксируется в каждом отчёте.
- Добавлены `manage.py drift-report`, `cam-drift-report`, включение drift diagnostics в daily report и fail-closed `DRIFT_*` настройки.
- Artifact/runtime/promotion contracts требуют `final-holdout-feature-probability-selected-calibration-reference-v2`; pre-1.17 artifacts необходимо переобучить.
- Новых migration нет; добавлены regression-тесты для PSI, calibration, coverage/missingness, failed inference jobs, runtime cohort compatibility и heartbeat degradation.

## 1.16.0 — 2026-07-05

- Добавлен строгий point-in-time market-context layer: OI log changes 1h/24h, mark/index basis и его часовая динамика, последняя settled funding rate/age и turnover-to-OI liquidity proxy.
- Progressive history backfill расширен hourly index-price candles и hourly open-interest observations; live market close по умолчанию обновляет mark/index/funding/OI.
- Training, walk-forward, final holdout, artifact и runtime переведены на `hourly-barrier-market-context-v4`; missing/duplicate/non-finite context блокируется без zero-fill.
- Историческая доступность честно ограничена exchange event/close timestamps; локальный receipt time задним числом не реконструируется. Live inference фильтрует все context rows по фактическому `available_at`.
- Добавлен same-temporal-split core-feature ablation с независимым refit; promotion gate блокирует final-holdout regression более 0.005 log-loss и требует non-inferiority минимум в двух из трёх walk-forward folds.
- Старые artifacts без context schemas/evidence отклоняются fail-closed; требуется завершить index/OI backfill и переобучить candidate.
- Новых migration и имён `.env` нет; defaults/recommended values `UNIVERSE_SYNC_MARK_PRICE` и `UNIVERSE_ENRICH_FUNDING_OI` изменены на `true`.
- Добавлены regression tests для temporal alignment, missing/duplicate context, bounded OI requests, artifact/gate contracts и operational defaults.

## 1.15.0 — 2026-07-05

- Added immutable prospective `advisory.selection_experiment_ledger` rows for every execution-plan version.
- Persisted a fixed pre-decision feature schema and tamper-evident SHA-256 without operator action or outcome leakage.
- Added chronological expanding out-of-sample logistic propensity diagnostics and stabilized inverse-probability-of-selection weighting.
- Reports now compare accepted-only, rejected/no-decision and all eligible counterfactual outcomes; class collapse, poor overlap, weak effective sample size and ledger corruption fail closed.
- Added `cam-selection-report`, `manage.py selection-report` and selection diagnostics to the daily report.
- Added migration `0011_selection_experiment`, eight regression tests and synchronized compliance, architecture, operator and QA documentation.

## 1.14.0 — 2026-07-05

- Added persisted point-in-time Bybit orderbook snapshots with exchange/source and local receipt timestamps.
- Added direction-aware bounded-depth market-fill simulation with FULL/PARTIAL/NO_FILL, VWAP, worst price and impact evidence.
- Execution-plan sizing now uses the minimum of turnover and bounded orderbook-depth caps and iterates entry geometry to complete-fill VWAP.
- Acceptance revalidates the full planned quantity against a fresh orderbook and recalculates incompatible, stale, partial-fill or adversely changed plans.
- Operator decisions persist exact depth/VWAP evidence and plan-to-decision latency.
- Added migration `0010_orderbook_exec_evidence`, retention policy, fail-closed configuration validation and regression tests.
- Historical orderbook backfill, queue position, limit-order fill probability and real exchange partial-fill lifecycle remain outside scope.

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
