# Patch 1.26.5 — observed experiment-period support

Date: 2026-07-05

## Problem

`scripts/backtest.py::policy_backtest` built experiment `period_returns` with one uninterrupted `date_range` from the first decision timestamp to the last modeled exit. When the holdout contained disjoint valid data segments, every unavailable calendar hour between them was silently emitted as a zero return.

Those invented zeros entered the aligned matrix used by CSCV/PBO, Deflated Sharpe and dependence-aware inference. They could increase `minimum_periods`, reduce measured volatility and change serial-dependence estimates without any market observation.

## Resolution

- Build the experiment period index from the union of each observed decision timestamp through its configured label horizon.
- Preserve genuine no-trade and holding hours inside those validated windows.
- Exclude hours that are not covered by any observed decision/label path.
- Persist and validate:
  - `observed_opportunity_period_count`;
  - `covered_period_count`;
  - `omitted_unobserved_calendar_period_count`.
- Raise the experiment return-path schema to `observed-opportunity-covered-hourly-capital-return-path-v2`.
- Reject legacy or arithmetically inconsistent success evidence before experiment governance.
- Convert invalid experiment evidence into a diagnostic failed promotion gate.

## Compatibility

- Alembic migration: none; head remains `0014_ui_exposure_ledger`.
- Public HTTP API: unchanged.
- `.env`: unchanged.
- Risk, cost and model-quality thresholds: unchanged.
- Active models continue running. Existing experiment families with successful v1 trials require new backtest trials/evidence before normal activation.

## Verification

- Red: 3 failures in `tests/unit/test_experiment_observed_period_path_2026_07_05.py`.
- Green targeted: 3 passed.
- Full suite: 618 passed, 4 skipped, 61 warnings.
- Static, compile, package and frontend checks are recorded in `docs/QA_REPORT.md` and the iteration report.
