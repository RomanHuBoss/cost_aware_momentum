# Changelog

## 1.49.0 — 2026-07-07

### Fixed

- Stopped treating sparse recommendation count as incomplete inference processing: retry now uses one terminal `symbol_outcomes` record per selected symbol.
- Separated production drift processing coverage (`processed / expected`) from recommendation density (`actionable / expected`).
- Removed the conditioned-on-published-signals actionability calculation that could report a sparse model as 100% actionable and trigger false quarantine.
- Bound drift reference actionability to final post-overlap `policy_trades / policy_candidates` under `published-policy-trades-per-symbol-opportunity-v1`.
- Raised production drift reference/report schemas to v4; legacy references require retraining.
- Added eight regressions; untouched 1.48.0 produced seven failures and one control pass.

## 1.48.0 — 2026-07-07

### Fixed

- Closed a sparse-pool concentration gap: one profitable under-supported interaction cell could keep the pooled tail positive while all remaining sparse cells were negative.
- Added deterministic leave-one-sparse-cell-out recomputation for economics and calibration, with exact omitted-cell identity, residual counts, weighted arithmetic and summary validation.
- Auto-activation now requires every residual sparse cohort to retain at least five trades, positive mean R and existing log-loss/Brier limits.
- Raised policy metric schema to v25 and interaction schema to `symbol-direction-regime-supported-cells-sparse-pool-jackknife-v2`; legacy artifacts require retraining.
- Added seven regressions; untouched 1.47.0 produced 6 failures and one independent sparse-pool masking demonstration.

## 1.47.0 — 2026-07-07

### Fixed

- Closed a symbol × direction × regime interaction-masking gap: positive per-symbol, per-direction and per-regime aggregates could hide a negative sufficiently supported cell.
- Added exact post-actionability/post-overlap interaction evidence with deterministic canonical cells and calibration/economics per cell.
- Added one preregistered sparse-cell pool so many under-supported cells are not silently ignored or converted into a combinatorial family of weak tests.
- Auto-activation now rejects negative or poorly calibrated supported cells, rejects an under-supported sparse pool, and verifies exact symbol/direction/regime sets against existing marginal evidence.
- Raised policy metric schema to v24, made interaction evidence mandatory at runtime and added nine regressions; untouched 1.46.0 produced 6 failures and one independent interaction-masking demonstration in the original seven-test red set.

## 1.46.0 — 2026-07-07

### Fixed

- Closed a directional masking gap: positive aggregate actionable economics could hide a negative or under-supported LONG or SHORT sub-policy after direction selection.
- Added exact per-direction opportunity-clock economics and actionable calibration for LONG and SHORT after actionability and overlap filtering.
- Auto-activation now rejects every traded direction with fewer than five trades, non-positive mean R, log loss above the existing limit or multiclass Brier above the existing limit.
- Added strict arithmetic/runtime validation, raised policy metric schema to v23 and made legacy artifacts require retraining.
- Added seven regressions; untouched 1.45.0 produced 6 failures and one independent directional-masking demonstration.

## 1.45.0 — 2026-07-07

### Fixed

- Closed a market-regime masking gap: positive aggregate actionable economics could hide a negative traded regime even after symbol and correlation-cluster jackknife checks passed.
- Added ex-ante decision-time regime classification from `ret_24h` and `atr_pct_14`; the high-volatility cutoff is learned only from the development window at the preregistered 75th percentile, while trend classification uses an immutable `|ret_24h / atr_pct_14| >= 1.0` rule.
- Added exact per-regime opportunity/trade accounting, realized mean R and actionable log-loss/Brier evidence after actionability and overlap filtering.
- Auto-activation now rejects any traded regime with fewer than five trades, non-positive mean R, log loss above the existing limit or multiclass Brier above the existing limit.
- Added strict arithmetic/runtime validation, raised policy metric schema to v22 and made legacy artifacts require retraining.
- Added seven regressions; untouched 1.44.0 produced 6 failures and one independent aggregate-masking demonstration.

## 1.44.0 — 2026-07-07

### Fixed

- Closed a correlated-symbol concentration gap left by the single-symbol jackknife: several dependent instruments could jointly create all final-holdout edge while removal of any one instrument remained positive.
- Added deterministic absolute-correlation connected components on exact actionable trade returns, requiring at least eight shared active observations and an immutable `|corr| >= 0.70` edge rule.
- Added leave-one-cluster-out opportunity-cohort recomputation that preserves the observed decision clock, zero-return no-trade hours and equal weighting of remaining simultaneous trades.
- Auto-activation now requires at least two dependence clusters and requires the worst leave-one-cluster-out mean R to remain strictly above the configured minimum policy mean R.
- Bound cluster evidence to the exact symbol-jackknife symbol set, added strict arithmetic/runtime validation, raised policy metric schema to v21 and made legacy artifacts require retraining.
- Added an eight-test regression suite; untouched 1.43.0 produced 6 failures and one independent masking demonstration in the original seven-test red set.

## 1.43.0 — 2026-07-07

### Fixed

- Closed a final-holdout cross-symbol concentration gap: aggregate policy mean R could pass while all positive edge came from one instrument.
- Added deterministic leave-one-symbol-out opportunity-cohort recomputation after actionability and overlap filtering, preserving zero-return no-trade hours and reweighting remaining simultaneous trades.
- Auto-activation now requires the minimum leave-one-symbol-out mean R to remain strictly above the configured minimum policy mean R; a one-symbol-only candidate therefore fails closed.
- Added immutable, arithmetically validated per-symbol evidence and mandatory runtime validation; policy metric schema is now v20 and legacy artifacts require retraining.
- Added seven regression tests with a red baseline of 6 failures and one independent masking demonstration.

## 1.42.0 — 2026-07-07

### Fixed

- Closed an econometric selection-bias gap between selected-direction calibration and the much smaller subset that actually passes actionability and overlap filters.
- Added final-holdout log loss and multiclass Brier for exact executed policy trades; the existing absolute ML limits now apply to that actionable cohort before activation.
- Bound actionable calibration rows exactly to `policy_trades` and reject missing, non-finite, malformed or internally inconsistent evidence fail-closed.
- Raised policy metric schema to v19 and made current actionable-calibration evidence mandatory at runtime, so legacy artifacts cannot be silently reused.
- Added seven red-to-green regressions, including a deterministic case where 130 well-calibrated non-trades mask 20 catastrophically overconfident trades under the old aggregate metric.

## 1.41.0 — 2026-07-07

- Fixed a promotion-gate selection-bias gap: the candidate is now judged on calibration of the exact LONG/SHORT direction selected by the policy, not only on metrics averaged across both counterfactual directions.
- Selected-direction log loss and multiclass Brier must be finite and remain within the existing absolute ML limits before activation.
- Added exact evidence arithmetic: final-holdout directional rows must equal twice the policy opportunity count, selected calibration rows must equal policy opportunities, and the immutable drift reference must describe the same directional holdout rows.
- Selected-cohort drift references can no longer be constructed implicitly from all-direction probabilities; an explicit selected-direction calibration reference is mandatory.
- Raised the immutable production-drift reference schema to v3 and selected calibration cohort schema to v2; legacy artifacts require retraining and remain fail-closed.
- Added six red-to-green regressions and reconciled existing fixtures with physically possible paired-direction counts.

## 1.40.0 — 2026-07-07

### Fixed

- Replaced the moving live entry band with an immutable decision-time zone centered on the exact confirmed decision-candle close.
- Applied the same `ENTRY_ZONE_ATR_FRACTION` gate to historical next-hour-open directional entry proxies, excluding symbol-hours whose executable proxy had already moved outside the evaluated decision geometry.
- Added `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS` and anchored signal expiry to `event_time`, preventing late catch-up publication from extending or re-anchoring an old decision.
- Bound entry-zone width and maximum publication lag to promotion-policy schema v4 and model-artifact entry-execution schema v2; incompatible legacy artifacts and active artifact/config drift fail closed.
- Added seven red → green regressions and updated affected artifact, lifecycle and label-integrity fixtures. No EV/RR, spread, risk, holdout or walk-forward threshold was relaxed.

## 1.39.0 — 2026-07-07

### Fixed

- Added a decision-time execution-input barrier for both hourly and universe-catchup inference: read-only account snapshot, active-universe order books and the ticker batch are refreshed immediately before signal/plan publication.
- Prevented startup catch-up from publishing a whole universe of profile plans before the first account sync or after order books had aged during long bootstrap/backfill work.
- Abort publication fail-closed when a configured read-only account refresh fails or a non-empty universe has zero successful/idempotently-covered orderbook refreshes.
- Preserve partial orderbook coverage diagnostics and all existing per-symbol stale checks; no freshness window, model gate, EV/RR threshold or risk limit was relaxed.
- Added five red → green regressions and updated the previous ticker-barrier tests to cover the combined account/orderbook/ticker publication boundary.

## 1.38.0 — 2026-07-07

- Fixed a confirmed dynamic-trainer preflight/fit mismatch: background fit now consumes the exact symbols persisted in the triggering `training_data_profile` instead of reloading an unlimited dynamic universe.
- Frozen last/mark/index candle loading at `preflight.end_time + horizon`, preventing new candles or universe changes arriving after authorization from changing the candidate dataset.
- Added fail-closed quality-gate checks for post-feature symbol scope, minimum symbol coverage and temporal advance beyond the approved preflight cutoff.
- Added six red → green regressions; no holdout, walk-forward, policy trade-rate, spread, EV/RR, leverage or risk threshold was relaxed.

## 1.37.0 — 2026-07-07

### Fixed

- Aligned dynamic-universe training and formal backtests with the exact live `MAX_SPREAD_BPS` executable gate instead of replaying every symbol admitted by the broader `UNIVERSE_MAX_SPREAD_BPS` discovery threshold.
- Derived execution-eligible historical cohorts from immutable per-symbol bid/ask spread evidence in each universe snapshot and recorded spread exclusions in replay evidence.
- Added `MAX_SPREAD_BPS` to immutable promotion-policy binding schema v3, so evidence produced under a different live spread contract cannot authorize normal activation.
- Built candidate training-data profiles from the actual post-replay model cohort, deduplicated to one source candle per symbol/hour, instead of the unfiltered source candle frame.
- Added six red → green regressions; no spread, quality, walk-forward, holdout, EV/RR or risk threshold was relaxed.

## 1.36.0 — 2026-07-07

### Added

- Added immutable PostgreSQL storage for exact registered model-artifact bytes, bound to registry UUID, version, SHA-256 and size.
- Added atomic SHA-verified file restoration before worker runtime selection, trainer recovery/promotion checks and manual/automatic registered activation.
- Added worker heartbeat, status API and trainer-dialog diagnostics for artifact archive and restore state.
- Added Alembic migration `0017_model_artifact_blobs`, append-only trigger and a 256 MiB fail-closed artifact limit.

### Fixed

- Removed the release-directory single point of failure where PostgreSQL retained an absolute `artifact_path` after the old release tree had been replaced or deleted.
- New candidate registration now archives exact bytes in the same transaction as registry, audit and outbox state; a failed archive rolls the registration back.
- Existing valid pre-1.36.0 artifacts are archived lazily on first worker/trainer/activation check; already missing bytes remain an explicit recovery-training case.
- Added eight red → green regression tests and one PostgreSQL integration contract; model quality, walk-forward, activation, EV/RR and risk gates are unchanged.

## 1.35.5 — 2026-07-07

### Fixed

- Added a fail-closed decision-time ticker refresh inside every actual hourly and universe-catchup inference transaction before signal publication.
- Moved the normal market-sync ticker write behind orderbook and newly-admitted-symbol backfill work and fetches a new Bybit ticker payload at that final boundary.
- Blocked inference before publication when a non-empty active universe produces zero persisted ticker rows instead of running against known-stale rows.
- Added structured stale-ticker diagnostics with actual age, configured maximum, source time and receipt time.
- Added five red → green regression tests; ticker freshness limits, model gates, EV/RR thresholds and risk limits are unchanged.

## 1.35.4 — 2026-07-06

### Fixed

- Replaced batch-wide exposure `409 Conflict` with independent terminal classification per event, so one stale/legacy card no longer rolls back valid evidence in the same request.
- Preserved original browser exposure identifiers across retry and limited retries to network, HTTP 429 and 5xx failures, preventing regenerated-event conflict loops.
- Added immutable exposure-to-opportunity verification across plan, signal, profile, version and chronology before duplicate acceptance and selection-bias analysis.
- Added latest-prior point-in-time orderbook selection for execution-plan construction and recommendation acceptance.
- Added latest-prior point-in-time account-equity selection for effective-capital, reconciliation and portfolio paths.
- Added an explicit fail-closed guard for missing acceptance validation evidence and hardened the process-tree timeout regression against startup jitter.
- Added nine regression tests; model quality, activation, EV/RR and risk thresholds are unchanged.

## 1.35.3 — 2026-07-06

### Fixed

- Closed immutable pending candidates with missing/corrupt artifacts, invalid horizon metadata or missing/stale deployment-policy binding instead of leaving the trainer permanently `BLOCKED`.
- Validated candidate path, SHA-256 and horizon before automatic experiment orchestration and persisted a terminal rejection gate with audit/outbox evidence.
- Continued the same scheduler iteration after stale-candidate closure so active-artifact recovery or the real data/quality wait reason is evaluated immediately.
- Decoupled governed recovery-training eligibility from baseline runtime fallback: production inference remains fail-closed while trainer/operator recovery can rebuild a missing or corrupted active artifact.
- Added seven regression scenarios for production recovery, candidate artifact integrity, legacy policy binding and scheduler continuation.

## 1.35.2 — 2026-07-06

### Fixed

- Replaced absolute-latest ticker reads with a shared latest-prior point-in-time query across signal publication, execution-plan construction and recommendation API/acceptance paths.
- Required both `source_time <= cutoff` and `received_at <= cutoff`, preventing a future-dated row from masking an older valid snapshot.
- Added deterministic tie-breaking by source time, receipt time and row id while retaining the existing stale-age checks after selection.
- Added red → green regression coverage for all three ticker consumers without changing model, policy, risk or activation thresholds.

## 1.35.1 — 2026-07-06

### Fixed

- Reprojected conditional TIMEOUT expectations from immutable stop-risk `R` onto each current executable entry/depth VWAP instead of reusing the signal-reference absolute return.
- Applied the same current-entry semantics during acceptance repricing, preventing stale TIMEOUT economics from falsely passing or failing `MIN_NET_EV_R`.
- Preserved legacy absolute TIMEOUT assumptions for signals without `timeout_return_r` and retained fail-closed validation for non-finite conditional estimates or invalid directional geometry.
- Raised execution-plan economics evidence to `tp-sl-timeout-current-entry-r-v2` and added LONG/SHORT, false-positive gate and plan-VWAP regressions.

## 1.35.0 — 2026-07-06

### Added

- Joined prospective candidate/live attrition evidence to exact `MarketSignal`, `SignalOutcome` and `PlanOutcome` rows.
- Added full-horizon-only TP/SL/TIMEOUT attribution by initial plan status, terminal stage and primary reason.
- Added descriptive valued-plan `counterfactual_r` counts, sign split, mean, median and sum without presenting them as actual execution PnL or causal estimates.
- Added fail-closed coverage checks for missing mature outcomes, conflicting labels, invalid valuation status/R pairs and incomplete plan outcome evidence.
- Added bounded database loading and regression coverage for outcome joins, maturity censoring, point-in-time `resolved_at` cutoffs and incomplete evidence.

## 1.34.2 — 2026-07-06

### Fixed

- Canonicalized universe eligibility snapshot `observed_at` and `recorded_at` to UTC before record hashing and revalidation.
- Prevented PostgreSQL session timezone rendering from producing false immutable-ledger hash mismatches that blocked trainer control and training-data profiling.
- Preserved fail-closed validation for actual snapshot tampering and added exact snapshot identity/timestamp diagnostics.
- Added regression coverage for timezone-invariant hash verification and invalid-row diagnostics.

## 1.34.1 — 2026-07-06

### Fixed

- Eliminated a research-to-production policy mismatch in expected funding semantics: live market-signal direction can no longer be flipped by a funding forecast absent from final-holdout promotion evidence.
- Kept fresh projected funding as a fail-closed execution-plan and acceptance overlay, preserving adverse-funding downside, net-edge and sizing checks.
- Added explicit persisted economics assumptions and regression coverage for the market-signal/execution separation.
- Rebuilt the release boundary and checksum manifest without caches, bytecode, egg-info or stale entries.

## 1.34.0 — 2026-07-06

- Added process-tree containment for automatic-experiment cancellation, timeout and failure cleanup.
