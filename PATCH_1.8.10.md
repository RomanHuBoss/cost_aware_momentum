# Patch 1.8.10 — quant/econometric correctness and actual open risk

## Problem

Audit of 1.8.9 reproduced multiple independent fail-open defects in funding signs, quantitative input validation, temporal/econometric metadata, model-artifact validation, execution-price revalidation, manual position risk and release integrity.

## Solution

- corrected signed funding for LONG/SHORT in live math, policy metrics and backtest;
- validated all cost inputs and projected-funding horizon/rate before arithmetic;
- validated complete directional metadata before ranking can hide a corrupt row;
- enforced label availability and barrier/return consistency in research backtest;
- made profit factor use the same cohort weights as equity/drawdown and included idle periods in concurrency averages;
- rejected malformed class distributions and invalid incumbent metrics in model promotion;
- required exact artifact schema/horizon/calibration metadata and a complete finite feature vector;
- rejected future ticker/spec data and recalculated plans at an adverse executable price;
- stored actual manual-entry risk and released remaining risk on partial close;
- valued counterfactual plan outcomes from the immutable plan snapshot;
- regenerated the release manifest.

## Database migration

Run:

```bash
python manage.py migrate
```

Revision `0006_manual_trade_remaining_risk` adds:

- `advisory.manual_trades.initial_stress_loss`;
- `advisory.manual_trades.remaining_stress_loss`;
- non-negative and remaining ≤ initial constraints.

Existing open/partial trades are backfilled conservatively from their plan risk, scaled by remaining quantity. New entries store risk recalculated from the actual entry price and quantity.

## Configuration

No new variables. Existing quantitative variables now reject non-finite or unsafe values at startup.

## Model compatibility

Artifacts must contain the exact current feature schema, a positive integer horizon, a non-empty calibration version, the expected class order and complete finite runtime features. An incompatible artifact must be retrained or recovered through the normal registry workflow; do not disable the validation.

## Verification

- baseline: `198 passed, 4 skipped`;
- added/expanded regression evidence: initial audit `33 failed`, follow-up audit `20 failed`; after fixes the corresponding suites pass;
- post-change: `252 passed, 4 skipped`;
- Ruff, compileall, pip check and frontend syntax checks pass;
- PostgreSQL integration tests were not run because no isolated `TEST_DATABASE_URL`/`POSTGRES_ADMIN_URL` was available.

## Limitations

This patch does not establish strategy profitability. Historical order-book execution, full walk-forward/PBO/DSR, live drift control and forward evidence remain separate work packages.
