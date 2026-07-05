# Architecture

## Fail-closed model activation flow 1.25.0

1. Candidate training computes the existing absolute and incumbent-relative quality gate before any activation request.
2. `register_and_activate_model_candidate` is the central atomic mutation boundary and calls `require_passed_quality_gate` before artifact loading, registry insertion or active-version update. Missing, failed or contradictory gate evidence therefore cannot be interpreted as approval by any caller.
3. Manual `train --activate` stores the computed gate. A failed candidate is registered inactive with `activation_requested=true`; the active model remains unchanged.
4. `model-registry activate` reads the immutable registry metrics and requires the persisted gate to be passed.
5. A reviewed emergency rollback to a model without passed evidence is possible only with an explicit override flag and non-empty incident reason. The original gate, override flag and reason are included in the append-only `MODEL_ACTIVATED` audit payload.
6. Artifact checksum, version, horizon and compare-and-swap active-version checks remain mandatory after governance validation.

This control does not weaken or replace experiment preregistration/PBO/DSR governance, and it does not automatically activate, roll back or place orders.

## Candidate/live attrition flow 1.24.0

1. Background trainer persists candidate version, quality-gate decision/reasons and activation outcome in `JobRun.details`.
2. Hourly and universe-catch-up inference persist one terminal record for every selected symbol: `SKIPPED`, `PUBLISHED` or `EXISTING_CURRENT_HOUR`.
3. Every initial execution plan stores immutable-at-creation attrition evidence in `sizing_snapshot.attrition`: schema, terminal stage, primary reason, contributing reasons and limiting cap.
4. `app/services/attrition.py` validates job denominators, duplicate/conflicting records and gate consistency, then deduplicates retries by `symbol × event_time`.
5. `scripts/attrition_report.py` writes `reports/candidate_live_attrition.json`; daily report embeds the same evidence. Legacy, failed or incomplete instrumentation gives `BLOCKED`.

The report is diagnostic only. It does not lower policy/risk gates, mutate model lifecycle, infer profitability or place orders. Evidence is prospective from 1.24.0; pre-release `JobRun` payloads are not reconstructed.

## Point-in-time funding interval replay 1.22.0

1. Instrument sync appends `reference.instrument_spec_history` only when the spec fingerprint changes, including `funding_interval_minutes` and `valid_from`.
2. Training data loading keeps both the latest interval map for compatibility and the complete positive interval history for selected symbols.
3. `FundingIntervalSchedule` normalizes duplicate/conflicting records, selects the interval effective at each UTC timestamp and records backward assumptions before the first observed spec.
4. `HistoricalFundingTimeline` validates settlement cadence against that schedule. Stable segments remain exact; a recorded interval transition is accepted only within a conservative maximum-gap bound, after which the new exact cadence applies.
5. Market-context construction divides funding age by the interval effective at each historical decision, so old 8-hour regimes are not evaluated as 4-hour regimes.
6. Candidate metrics and artifacts persist funding/context schedule evidence. Promotion and runtime require the new schemas and point-in-time source; older artifacts fail closed.
7. The change remains research/advisory-only. It does not forecast funding, place orders or alter account-dependent execution sizing.

Data flow: instrument spec observations → point-in-time interval schedule → settlement replay and funding-age features → dataset → candidate metrics/artifact → promotion/runtime validation.


## Verified recommendation UI exposure 1.21.0

1. Every execution-plan version still creates an immutable ex-ante `selection_experiment_ledger` row in the plan transaction.
2. The browser renders recommendation tiles with exact `plan_id` and `plan_version` metadata.
3. `IntersectionObserver` starts a dwell timer only when at least 50% of the tile is visible and `document.visibilityState` is `visible`.
4. After one second, the authenticated browser sends a CSRF-protected batch event containing a random client event ID, ephemeral page instance ID, UTC observation time, viewport ratio and dwell time.
5. `POST /api/v1/recommendations/exposures` verifies the immutable opportunity, version and time bounds, then inserts the first exposure with PostgreSQL `ON CONFLICT DO NOTHING` idempotency.
6. `advisory.selection_exposure_ledger` is append-only: canonical SHA-256 covers all evidence fields and a PostgreSQL trigger rejects UPDATE/DELETE.
7. Selection analysis uses exposure time, not plan creation time, and excludes unexposed opportunities from the propensity cohort. Coverage below the configured floor returns `LOW_EXPOSURE_COVERAGE`.
8. Exposure is research evidence only. It never marks a plan accepted/viewed, changes risk, mutates the model or calls Bybit order endpoints.

Data flow: plan creation → ex-ante opportunity → visible tile dwell → authenticated immutable first exposure → decision/outcome join → exposure-conditioned propensity/IPSW report.

## Formal experiment-family preregistration 1.20.0

1. `backtest --prepare-preregistration` builds the exact final-test cohort fingerprint and complete current configuration, writes a draft JSON, then exits before `STARTED`, prediction or policy evaluation.
2. The researcher replaces placeholders, enumerates every permitted search value and commits the primary metric, PBO/DSR/dependence policy, stopping budget/deadline and objective exclusions.
3. `experiment-preregister` validates the specification and inserts one `research.experiment_family_registrations` row only when no trial event exists for the family.
4. A canonical record hash covers family, UTC registration time, normalized specification and release version. A PostgreSQL trigger rejects UPDATE and DELETE.
5. `append_experiment_event(..., STARTED)` locks the registration row, verifies its hash, validates every fixed/search parameter and enforces the stopping budget/deadline before writing any trial event.
6. The STARTED event stores the preregistration record hash and selected search values; terminal events require the same registration.
7. `experiment-report` reconstructs the ledger only under that immutable contract. Threshold overrides must equal the registered values; legacy unregistered families return `BLOCKED_UNREGISTERED_FAMILY`.
8. Registration is prospective governance. It does not alter model training, inference, risk, execution or active-model state.

Data flow: exact unevaluated cohort/configuration → draft specification → immutable PostgreSQL registration → validated STARTED event → aligned returns/terminal event → preregistered PBO/DSR/dependence report.


## Dependence-aware research inference 1.19.0

Experiment-family analysis now separates model-search multiplicity from time-series dependence:

1. CSCV/PBO still compares all disclosed variants on one aligned hourly grid.
2. The selected return path receives Bartlett/Newey–West long-run variance; its implied effective observation count replaces nominal `n` in DSR inference.
3. Moving-block bootstrap resamples overlapping contiguous return blocks and publishes percentile intervals for mean return and non-annualized Sharpe.
4. The effective block length is at least the declared trading horizon. Fewer than the configured independent blocks yields a blocked report.
5. `READY` additionally requires positive lower HAC mean, block-bootstrap mean and block-bootstrap Sharpe bounds. This changes only research classification; active-model lifecycle is untouched.

Operator-selection inference uses `signal_id` as the dependence cluster. Every plan version of one signal is assigned to the same propensity OOS block, and clusters whose observation interval overlaps the test start are purged from training. A chronological moving-block bootstrap resamples whole signal clusters and reports uncertainty for eligible mean, selected mean, IPSW mean and selected-subset bias. The bootstrap conditions on previously fitted OOS propensities and remains descriptive, not causal.

## Research experiment-selection flow 1.18.0

1. Backtest validates the immutable model artifact and constructs the exact final-test dataset.
2. Release 1.20.0 requires an explicit already-preregistered family; automatic family derivation is removed from executable trials.
3. Before model evaluation, PostgreSQL receives a `STARTED` event containing the sanitized configuration and canonical SHA-256.
4. The backtest simulates capital sleeves on a common hourly grid, explicitly retaining zero-return hours so alternatives are alignable.
5. Completion appends exactly one `SUCCEEDED` event with period returns and summary evidence or one `FAILED` event with bounded diagnostics. Events link through `previous_event_hash`.
6. Family reconstruction verifies every event and hash chain, discloses repeated attempts, deduplicates identical configuration hashes and blocks unresolved failed/open configurations.
7. The analysis builds a period-by-configuration matrix, applies contiguous CSCV/PBO, estimates the correlation-implied number of independent trials and calculates Deflated Sharpe for the selected non-annualized-Sharpe variant.
8. Thresholds classify the report as `READY` or `REJECTED`; structural insufficiency produces a `BLOCKED_*` status. `automatic_model_action=none` and `profitability_claimed=false` are invariant.

Data flow: validated artifact + final-test cohort → STARTED event → aligned hourly returns → terminal event → verified family matrix → PBO/DSR governance report.

Boundary: this is prospective research governance. It does not recreate pre-1.18 experiments or retroactively preregister pre-1.20 families, alter the active model or become evidence of live profitability. Dependence-aware inference is added by release 1.19.0 and formal family preregistration by 1.20.0.

## Production drift flow 1.23.0

1. Candidate training uses the untouched final holdout to create fixed histogram references for the 17 base features and all LONG/SHORT probability vectors.
2. Policy evaluation selects one direction per symbol/timestamp using the same ex-ante economics as production and stores selected-cohort log-loss/Brier plus actionability density. This avoids comparing production selected outcomes with an all-direction calibration baseline.
3. The immutable reference is stored in both artifact and model-registry metrics and is checked by quality gate and runtime.
4. Every published signal stores the common feature vector and both directional probability vectors under `directional_predictions`; the selected signal probabilities remain the calibration observation.
5. Hourly monitor queries only signals from the active model version and the configured trailing window. Feature/probability/actionability diagnostics use the full window, while calibration uses only signals whose `event_time + horizon_hours` is not later than report time.
6. Early resolved TP/SL outcomes from still-immature signals are excluded from calibration. Every full-horizon mature signal must have exactly one `SignalOutcome`; unresolved or duplicate mature evidence blocks calibration and is disclosed in `outcome_coverage`.
7. Fixed holdout bins are used for feature/probability PSI. Coverage comes from hourly inference JobRun scope and completion counts; failed jobs or invalid accounting block the report.
8. Reports classify evidence as `OK`, `WARN`, `CRITICAL` or `BLOCKED`. `CRITICAL/BLOCKED` changes worker heartbeat to `DEGRADED`.
9. The monitor is observational: `automatic_model_action=none`. It does not activate, deactivate, roll back, retrain or weaken any model/policy/risk gate.

Data flow: final holdout → immutable reference → active-version signals/jobs → full-horizon maturity partition → complete mature outcomes → fixed-bin/calibration drift evaluation → JobRun/heartbeat/JSON report.

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
