# Changelog

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
