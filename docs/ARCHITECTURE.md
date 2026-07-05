# Architecture

## Research experiment-selection flow 1.18.0

1. Backtest validates the immutable model artifact and constructs the exact final-test dataset before experiment registration.
2. A deterministic family identifier is derived from horizon and final-test cohort fingerprint unless the researcher supplies a predeclared family.
3. Before model evaluation, PostgreSQL receives a `STARTED` event containing the sanitized configuration and canonical SHA-256.
4. The backtest simulates capital sleeves on a common hourly grid, explicitly retaining zero-return hours so alternatives are alignable.
5. Completion appends exactly one `SUCCEEDED` event with period returns and summary evidence or one `FAILED` event with bounded diagnostics. Events link through `previous_event_hash`.
6. Family reconstruction verifies every event and hash chain, discloses repeated attempts, deduplicates identical configuration hashes and blocks unresolved failed/open configurations.
7. The analysis builds a period-by-configuration matrix, applies contiguous CSCV/PBO, estimates the correlation-implied number of independent trials and calculates Deflated Sharpe for the selected non-annualized-Sharpe variant.
8. Thresholds classify the report as `READY` or `REJECTED`; structural insufficiency produces a `BLOCKED_*` status. `automatic_model_action=none` and `profitability_claimed=false` are invariant.

Data flow: validated artifact + final-test cohort → STARTED event → aligned hourly returns → terminal event → verified family matrix → PBO/DSR governance report.

Boundary: this is prospective research governance. It does not recreate pre-1.18 experiments, correct serial dependence with HAC/bootstrap inference, alter the active model or become evidence of live profitability.

## Production drift flow 1.17.0

1. Candidate training uses the untouched final holdout to create fixed histogram references for the 17 base features and all LONG/SHORT probability vectors.
2. Policy evaluation selects one direction per symbol/timestamp using the same ex-ante economics as production and stores selected-cohort log-loss/Brier plus actionability density. This avoids comparing production selected outcomes with an all-direction calibration baseline.
3. The immutable reference is stored in both artifact and model-registry metrics and is checked by quality gate and runtime.
4. Every published signal stores the common feature vector and both directional probability vectors under `directional_predictions`; the selected signal probabilities remain the calibration observation.
5. Hourly monitor queries only signals from the active model version and the configured trailing window. It joins only already resolved `SignalOutcome` rows.
6. Fixed holdout bins are used for feature/probability PSI. Coverage comes from hourly inference JobRun scope and completion counts; failed jobs or invalid accounting block the report.
7. Reports classify evidence as `OK`, `WARN`, `CRITICAL` or `BLOCKED`. `CRITICAL/BLOCKED` changes worker heartbeat to `DEGRADED`.
8. The monitor is observational: `automatic_model_action=none`. It does not activate, deactivate, roll back, retrain or weaken any model/policy/risk gate.

Data flow: final holdout → immutable reference → active-version signals/jobs/outcomes → fixed-bin drift evaluation → JobRun/heartbeat/JSON report.

## Point-in-time market-context flow 1.16.0

1. Worker progressively stores confirmed hourly `last`, `mark` and `index` candles, hourly `OpenInterest` rows and actual funding settlements from public/read-only Bybit endpoints.
2. Training loads the five source families in one `TrainingMarketData` bundle. Historical joins use exact exchange event/close timestamps; local receipt timestamps cannot be reconstructed for old public history and this limitation is persisted in artifact metadata.
3. `build_market_context_frame()` creates seven ex-ante features: OI log changes 1h/24h, mark/index basis and 1h basis change, latest already-settled funding rate and normalized age, turnover/OI notional liquidity proxy.
4. Exact current/lagged OI and exact current/previous basis are required. Funding is backward-only and must lie within the instrument funding interval. Missing, duplicate, non-positive or non-finite input leaves the timestamp incomplete; no zero-fill or forward use is allowed.
5. `make_barrier_dataset()` attaches context at the decision candle close before LONG/SHORT scenario duplication. Context never uses label path, future funding, future mark path or operator outcome.
6. Final holdout and each purged expanding walk-forward fold independently refit both the enriched model and a comparator with context columns zeroed on the same timestamps. Gate permits no more than 0.005 final log-loss regression and requires context non-inferiority in at least two of three folds.
7. Artifact/runtime require exact feature order, context schema, availability schema and ablation schema. Pre-1.16 artifacts fail closed.
8. Live inference queries only rows with `available_at <= available_cutoff`; incomplete current context skips the symbol rather than falling back to stale/zero values.

Data flow: public market GET → PostgreSQL event/receipt timestamps → strict context join → enriched features → temporal training/ablation → immutable artifact → receipt-filtered live inference.

## Operator-selection evidence flow 1.15.0

1. `create_execution_plan()` completes all market, capital, liquidity and risk calculations.
2. Before any operator action, the same transaction inserts one `selection_experiment_ledger` row keyed by `plan_id`.
3. The row stores eligibility, immutable identifiers, a fixed numeric pre-decision feature vector and canonical SHA-256. It never stores decision or outcome.
4. Existing `operator_decisions` records ACCEPT/REJECT; absence of a terminal decision becomes `NO_DECISION` only at report time.
5. Existing `plan_outcomes` supplies counterfactual R for all valued plan versions, including unselected opportunities.
6. Reporting verifies every row hash, uses all eligible valued plans as the primary benchmark and fits propensity models only on earlier observations.
7. Stabilized IPSW is emitted only with two classes, temporal OOS scores, overlap and adequate effective sample size.
8. The estimator is descriptive selection diagnostics. It does not infer a causal benefit of accepting a plan and does not replace exchange-confirmed fill P&L.

Data flow: plan calculation → immutable ex-ante ledger → operator decision/no-decision → counterfactual outcome → chronological propensity diagnostics → JSON report.

## Границы

Система advisory-only. Bybit client выполняет public/read-only GET operations; order placement, amend и cancel отсутствуют. PostgreSQL является единственным state store. API/UI, inference worker и trainer запускаются отдельными процессами.

## Point-in-time execution flow 1.14.0

1. Inference worker запрашивает public/read-only Bybit REST orderbook для активных symbols с bounded depth.
2. Normalizer проверяет symbol, timestamps, ordering, positive levels и uncrossed geometry; сохраняются matching-engine/source time и local receipt time.
3. PostgreSQL хранит immutable prospective snapshots; natural key `symbol + source_time + update_id` допускает перезапуск биржевого сервиса и повтор `u`.
4. Execution plan выбирает asks для LONG или bids для SHORT и вычисляет доступный notional внутри `MAX_VWAP_IMPACT_BPS`.
5. Position sizing использует минимум turnover cap и depth cap, затем пересчитывает full-fill VWAP, stop-distance risk и qty до устойчивого результата.
6. `PARTIAL`, `NO_FILL`, stale/future snapshot и несовместимый plan evidence блокируют действие.
7. Acceptance повторяет simulation на свежем snapshot для всей qty; при изменении создаётся новая plan version.
8. Operator decision сохраняет source/receipt timestamps, update/sequence, VWAP, worst price, impact и latency.
9. Retention удаляет snapshots старше `ORDERBOOK_RETENTION_HOURS`; архив до 1.14.0 не восстанавливается.

Граница: это immediate-market prospective evidence. Queue position, RPI liquidity, historical depth backfill, limit-order fill probability и реальный OMS partial-fill lifecycle не входят в текущую архитектуру.

## Training and validation data flow 1.13.0

1. Confirmed hourly last/mark/index candles, hourly open interest, фактические funding settlements и instrument funding interval загружаются из PostgreSQL одним `TrainingMarketData` bundle (`app/ml/lifecycle.py`).
2. `build_feature_frame()` строит десять point-in-time OHLCV features; `build_market_context_frame()` по тому же decision close добавляет семь OI/basis/settled-funding/liquidity features. Future mark path и future funding не входят в features.
3. `make_barrier_dataset()` формирует direction-specific `TP / SL / TIMEOUT` labels по last-price OHLC с execution spread proxy и привязывает funding aggregates к full horizon и actual modeled exit.
4. Для каждого label строится точная hourly mark-price timeline до modeled last-price exit. Gap, duplicate, неверная OHLC или несовпадение `open_time/close_time` исключают весь LONG/SHORT cohort fail-closed.
5. `simulate_intrahorizon_margin_path()` независимо восстанавливает directional mark-to-market, MAE/MFE, minimum equity и conservative isolated-margin liquidation proxy. Funding применяется по фактической границе settlement; выход на open не использует последующие экстремумы bar.
6. Future mark path не меняет target class, probabilities, direction ranking, RR, EV или actionability. Она может только сократить realized exit и заменить realized gross return/funding window после ex-ante выбора.
7. `chronological_split()` резервирует отдельный purged train/calibration/final-holdout split; final holdout используется один раз для candidate/incumbent и absolute gates.
8. Development region заканчивается до начала final holdout по `label_end_time`.
9. `expanding_walk_forward_splits()` строит три последовательных fold: expanding train, rolling calibration и более поздний неперекрывающийся test. Label overlap удаляется, вокруг границ применяется horizon embargo.
10. В каждом fold создаётся новый `TemporalCalibratedBarrierModel`; preprocessing fit выполняется только на fold train, calibration — только на fold calibration.
11. Fold-level ML/policy metrics, context-ablation evidence, historical-funding evidence и intrahorizon-margin evidence сохраняются в immutable candidate artifact. Quality gate заново проверяет исходные records, временной порядок и арифметическую согласованность.
12. Runtime требует feature/context/ablation, label, temporal, walk-forward, funding и margin-path schemas. Candidate/incumbent comparison разрешён только при одинаковых entry/barrier, leverage и liquidation-reserve assumptions.

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
