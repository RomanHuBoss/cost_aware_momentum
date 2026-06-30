# Patch 1.8.13 — open-gap metadata propagation

Date: 2026-06-30

## Problem

Version 1.8.12 added open-first barrier handling and stored `exit_at_open` in the labeled dataset, but `app.ml.training.chronological_split()` omitted that field from final-holdout metadata. Downstream policy/backtest validation then silently substituted `False` when the field was absent. As a result, an opening-gap exit could be shifted from the candle open to its close during holdout evaluation even though the source label contained the correct timestamp semantics.

The affected metrics still advertised the v3 policy schema, so corrected metrics and potentially affected 1.8.12 metrics could be treated as compatible by the model-promotion gate.

## Solution

- `chronological_split()` now requires boolean `exit_at_open` for every labeled row and preserves it in `DatasetSplit.test_meta`.
- `validate_policy_evaluation_metadata()` now rejects metadata without `exit_at_open` instead of silently applying close-time semantics.
- The policy metric schema is now `exit-time-open-gap-propagated-horizon-sleeves-v4`.
- Auto-activation rejects v3 policy metrics; candidate/incumbent evidence must be recomputed under v4.
- Regression coverage exercises the real dataset → split → policy-metadata path, direct missing-field validation, and lifecycle schema isolation.

## Compatibility

- No PostgreSQL migration.
- Alembic head remains `0006_manual_trade_remaining_risk`.
- No new or changed environment variables.
- API/UI/Bybit contracts are unchanged.
- Manual research callers constructing `DatasetSplit.test_meta` must provide boolean `exit_at_open` for every row.
- Retrain candidates and recompute incumbent/candidate holdout and research backtest metrics before comparison.

## Verification

Baseline 1.8.12:

- `python -m pip check`: PASSED
- `python -m compileall -q app scripts tests manage.py`: PASSED
- `python -m ruff check .`: PASSED
- `python -m pytest -q`: 272 passed, 4 skipped, 19 warnings
- `node --check web/js/app.js`: PASSED
- release integrity: 147 files checked, 147 manifest entries

Red evidence on the unmodified behavior:

- split propagation test: failed because `exit_at_open` was absent from `test_meta`;
- split contract test: failed because missing `exit_at_open` was accepted;
- policy metadata contract test: failed because missing `exit_at_open` was converted to `False`;
- lifecycle schema test: failed because v4 was rejected while affected v3 was still current.

Post-change:

- focused regressions: PASSED;
- full unit/default suite: 276 passed, 4 skipped, 19 warnings;
- PostgreSQL integration tests and runtime doctor: not run because no isolated test database/runtime configuration was available.

Technical correctness and green tests do not establish strategy profitability.
