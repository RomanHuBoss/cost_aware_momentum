# Patch 1.46.0 — Policy directional robustness

## Problem

Release 1.45.0 checked aggregate actionable economics, exact actionable calibration, symbol concentration, correlation-cluster concentration and market regimes. It still allowed a profitable LONG sub-policy to offset a systematically negative SHORT sub-policy, or vice versa. Aggregate and regime metrics could therefore pass while one direction actually shown to the operator was harmful.

## Reproduced defect

A deterministic 20-opportunity cohort was built with ten LONG trades at `+1.0 R` and ten SHORT trades at `-0.20 R`. Aggregate result remained `+0.40 R`. On the complete observed opportunity clock, LONG contributed `+0.50 R` and SHORT contributed `-0.10 R`. Untouched 1.45.0 had no direction evidence, activation-gate enforcement or runtime validation. The regression set produced `6 failed, 1 passed`; the passing test independently demonstrated the masking effect.

## Solution

- Added `actionable-policy-direction-opportunity-cohort-v1`.
- Exact post-actionability/post-overlap trades are partitioned into LONG and SHORT.
- Each direction is recomputed on the complete observed opportunity clock; hours without that direction remain zero-return cohorts.
- Evidence stores opportunities, trade/no-trade cohorts, trade counts/fractions, opportunity-weighted realized mean R and exact actionable log loss/Brier.
- Every traded direction must have at least five trades, positive mean R under the configured minimum and calibration within the existing absolute limits.
- Added strict schema, canonical ordering, count, fraction, summary and runtime validation.
- Policy metric schema increased from v22 to v23.

## Compatibility

No migration, API change or new environment variable is required. Pre-1.46 artifacts lack mandatory direction evidence and require retraining. Existing economics, risk, regime, symbol and cluster thresholds are unchanged.

## Verification

- Baseline: `797 passed, 8 skipped`.
- Red set on untouched 1.45.0: `6 failed, 1 passed`.
- Direction regression file after implementation: `7 passed`.
- Focused lifecycle/runtime suite: `36 passed`.
- Full post-change suite: `804 passed, 8 skipped`.
- Ruff, compileall and JavaScript syntax: passed.
- PostgreSQL integration tests were skipped because no isolated test database was configured.

## Residual limitations

The check is directional, not a full symbol × direction × regime interaction model. It does not establish causal profitability, future calibration, fill realism or forward performance.
