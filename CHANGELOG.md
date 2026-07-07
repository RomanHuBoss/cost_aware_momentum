# Changelog

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
