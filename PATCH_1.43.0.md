# Patch 1.43.0 — Policy symbol jackknife robustness

## Problem

The final-holdout policy gate validated aggregate opportunity-cohort return, dependence-aware temporal uncertainty, walk-forward stability and actionable calibration, but it did not test whether the result depended on one traded symbol. A candidate could therefore have positive aggregate mean R and positive temporal lower bound while one instrument supplied all gains and the remaining traded universe was loss-making.

## Reproduced defect

A deterministic two-symbol holdout produced aggregate `policy_realized_mean_r = +0.4 R`. Removing `WINUSDT` and recomputing the same observed opportunity clock produced `-0.2 R`; removing `LOSSUSDT` produced `+1.0 R`. Version 1.42.0 emitted no symbol-robustness evidence and both quality gate and runtime accepted artifacts without it.

## Solution

- Added `leave-one-symbol-out-opportunity-cohort-v1`.
- The calculation runs after actionability and single-active-trade-per-symbol overlap filtering.
- For each traded symbol, its trades are removed, remaining simultaneous trades are equally reweighted, and every observed no-trade hour remains a zero return.
- Evidence contains exact symbol counts, trade counts/fractions and each leave-one-out policy mean.
- Arithmetic, normalized symbols, uniqueness, sorted order and summary extrema are validated fail-closed.
- Auto-activation requires at least two traded symbols and requires the worst leave-one-out mean R to be strictly above `AUTO_TRAIN_MIN_POLICY_REALIZED_MEAN_R`.
- Runtime rejects missing or malformed evidence.
- Policy metric schema increased from v19 to v20.

## Compatibility

No database migration, API change or new environment variable is required. Artifacts created before 1.43.0 do not contain the new evidence and must be retrained. No existing ML, calibration, EV/RR, spread, walk-forward, cost or risk threshold was relaxed.

## Verification

- Red: `6 failed, 1 passed` on untouched 1.42.0.
- Green focused suite: `46 passed`.
- Full post-change suite: `782 passed, 8 skipped`.
- Ruff, compileall and JavaScript syntax: passed.
- PostgreSQL integration tests were skipped because no isolated test database was configured.

## Residual limitations

This jackknife tests dependence on one symbol in the final holdout. It does not establish symbol-by-symbol calibration, sector/correlation-cluster independence, market-regime stability, exact historical fills or live profitability.
