# Patch 1.45.0 — Policy market-regime robustness

## Problem

Release 1.44.0 protected the final holdout against single-symbol and correlation-cluster concentration, but aggregate actionable economics and calibration could still hide a losing market regime. A profitable trend cohort could offset a negative range or high-volatility cohort, allowing a candidate to pass despite systematically harmful recommendations in one state actually traded by the policy.

## Reproduced defect

A deterministic 20-opportunity cohort was built with ten UPTREND trades at `+1.0 R` and ten RANGE trades at `-0.20 R`. Aggregate mean remained `+0.40 R`, while the RANGE regime was negative. Untouched 1.44.0 had no regime evidence, quality-gate enforcement or runtime validation. The original regression set produced `6 failed, 1 passed`; the passing test independently demonstrated the masking effect.

## Solution

- Added `decision-time-development-quantile-market-regimes-v1`.
- Regimes use only decision-time features already available to the model: market-median `ret_24h` and `atr_pct_14` across selected symbols.
- The HIGH_VOLATILITY cutoff is the 75th percentile of market-median ATR percentage calculated on development data only.
- Non-high-volatility observations are UPTREND/DOWNTREND when `ret_24h / atr_pct_14` is at least `+1.0` or at most `-1.0`; all other observations are RANGE.
- For every observed regime, evidence stores opportunity cohorts, trade cohorts, no-trade cohorts, trades, trade fraction, opportunity-weighted realized mean R and exact actionable calibration.
- Every traded regime must have at least five trades, positive mean R under the configured minimum and log-loss/Brier within the existing absolute limits.
- Added strict count, fraction, ordering, summary and runtime validation.
- Policy metric schema increased from v21 to v22.

## Compatibility

No migration, API change or new environment variable is required. Pre-1.45 artifacts lack mandatory regime evidence and require retraining. Existing EV/RR, spread, holdout, walk-forward, funding, cost, risk, symbol and cluster thresholds are unchanged.

## Verification

- Baseline: `790 passed, 8 skipped`.
- Red set on untouched 1.44.0: `6 failed, 1 passed`.
- Regime regression file after implementation: `7 passed`.
- Focused lifecycle/runtime suite: `51 passed`.
- Full post-change suite: `797 passed, 8 skipped`.
- Ruff, compileall and JavaScript syntax: passed.
- PostgreSQL integration tests were skipped because no isolated test database was configured.

## Residual limitations

The regime definition is a fixed statistical partition, not a causal market-state model. Threshold stability on future data, per-symbol-by-regime calibration, sub-hour execution and live forward profitability remain unverified. A candidate is not required to trade multiple regimes; it is required to be sufficiently supported and non-negative in each regime it actually trades.
