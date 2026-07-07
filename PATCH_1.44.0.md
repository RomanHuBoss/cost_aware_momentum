# Patch 1.44.0 — Policy correlation-cluster jackknife robustness

## Problem

Release 1.43.0 removed each traded symbol independently, but that test can miss group concentration. Two or more strongly dependent instruments can jointly supply all final-holdout gains: removing either one leaves the other profitable proxy, while removing the whole dependent group exposes an unprofitable residual universe.

## Reproduced defect

A deterministic three-symbol actionable cohort was built with two near-perfectly correlated winners and one persistent loser. The existing symbol jackknife remained positive after removal of every single symbol, but removing the connected winner component produced `-0.20 R` on the unchanged opportunity clock. Untouched 1.43.0 had no cluster calculation, quality-gate enforcement or runtime evidence validation.

## Solution

- Added `absolute-correlation-components-leave-one-cluster-out-opportunity-cohort-v1`.
- Symbols are connected when absolute Pearson correlation of realized actionable-trade R is at least `0.70` on at least eight timestamps where both traded.
- Transitive connected components form deterministic sorted dependence clusters.
- Each cluster is removed in full; remaining simultaneous trades are equally reweighted and every observed no-trade hour remains zero.
- Auto-activation requires at least two clusters and requires the worst leave-one-cluster-out policy mean R to remain strictly above `AUTO_TRAIN_MIN_POLICY_REALIZED_MEAN_R`.
- Evidence validation checks immutable configuration, IDs, sorted/unique symbols, counts, fractions, extrema and exact agreement with symbol-jackknife symbols.
- Runtime rejects absent, malformed or legacy evidence.
- Policy metric schema increased from v20 to v21.

## Compatibility

No migration, API change or new environment variable is required. Pre-1.44 artifacts lack mandatory cluster evidence and require retraining. Existing calibration, EV/RR, spread, holdout, walk-forward, cost and risk limits are unchanged.

## Verification

- Baseline: `782 passed, 8 skipped`.
- Original red set on untouched 1.43.0: `6 failed, 1 passed`.
- Final cluster regression file: `8 passed`.
- Full post-change suite: `790 passed, 8 skipped`.
- Ruff, compileall and JavaScript syntax: passed.
- PostgreSQL integration tests were skipped because no isolated test database was configured.

## Residual limitations

Clusters are inferred from realized final-holdout returns, not an ex-ante sector taxonomy. Pairs with fewer than eight simultaneous actionable observations remain disconnected. The gate does not yet provide market-regime stratification, per-symbol calibration or causal proof of profitability.
