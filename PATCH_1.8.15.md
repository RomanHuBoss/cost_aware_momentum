# Patch 1.8.15 — executable quote and target-contract integrity

## Problem

The 1.8.14 release had four connected production-contract defects:

1. crossed top-of-book quotes (`ask < bid`) produced a negative spread and could reach direction ranking or recommendation acceptance;
2. raw `NaN`/`Infinity` ticker values could raise `decimal.InvalidOperation` and abort an entire universe/ticker batch;
3. the operator entry-state used last price while acceptance used executable ask/bid;
4. signals advertised a 70/30 TP1/TP2 plan although labels, outcome probabilities, EV/R, sizing and counterfactual valuation modeled only TP1.

## Solution

- Added one finite, positive, non-crossed bid/ask validator and reused it in signal and accept paths.
- Made dynamic-universe parsing reject non-finite values without arithmetic exceptions.
- Made ticker synchronization isolate malformed rows and represent invalid top-of-book pairs as unavailable.
- Switched entry-state presentation to executable ask for LONG and bid for SHORT.
- Disabled the unmodeled second target: new signals store `take_profit_2 = NULL`, `tp1_weight = 1`, and API details expose TP1 at 100%.

## Compatibility

- Version: `1.8.15`.
- Alembic head remains `0006_manual_trade_remaining_risk`.
- No migration and no `.env` change.
- Legacy nullable TP2 columns remain in the schema for backward compatibility.
- Model artifacts and policy metric schema v5 are unchanged; retraining is not required.

## Verification

Baseline in an isolated `.[dev]` environment:

- `pip check`: passed;
- compileall: passed;
- Ruff: passed;
- pytest: `282 passed, 4 skipped, 19 warnings`;
- Node syntax: passed;
- input release integrity: `152/152`.

Red → green:

- first focused run: `5 failed`;
- additional executable-side UI regression: `1 failed`;
- corrected focused suite: `6 passed`.

Post-change full suite before release packaging: `288 passed, 4 skipped, 19 warnings`.

## Limitations

- PostgreSQL integration tests and `manage.py doctor` were not run because no safe disposable PostgreSQL configuration or application `.env` was available.
- Weighted partial exits remain unimplemented. Re-enabling TP2 requires one coherent label, policy, sizing and outcome-accounting model.
- Technical correctness does not demonstrate economic profitability.
