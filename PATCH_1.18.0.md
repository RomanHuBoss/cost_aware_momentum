# Patch 1.18.0 — experiment overfitting governance

## Problem

Research evidence recorded individual backtest summaries but did not prove disclosure of every tried configuration and did not quantify multiple-testing/backtest-overfitting risk. A favourable Sharpe from the best tried variant could therefore be reported without PBO, Deflated Sharpe or a tamper-evident family-level trial history.

## Solution

- Added append-only `research.experiment_events` with `STARTED` and exactly one `SUCCEEDED/FAILED` terminal event per trial.
- Canonical configuration hashes and chained event hashes detect mutation and preserve attempt order.
- Backtests persist an aligned hourly return path, including hours without realized exits.
- Added contiguous CSCV/PBO, correlation-adjusted effective trial count and Deflated Sharpe probability.
- Governance blocks on incomplete disclosure, failed/open variants, insufficient trials/periods, unaligned return grids, invalid returns, redundant trials or ledger corruption.
- Added `experiment-report` CLI. Reports never mutate model state or claim profitability.

## Database migration

Apply migration:

```bash
python manage.py migrate
```

Expected Alembic head: `0012_experiment_selection`. Downgrade removes only `research.experiment_events`; export its evidence before rollback if it must be retained.

## Configuration

Add/review:

```env
EXPERIMENT_PBO_SEGMENTS=6
EXPERIMENT_MIN_TRIALS=4
EXPERIMENT_MIN_PERIODS=60
EXPERIMENT_MAX_PBO=0.20
EXPERIMENT_MIN_DSR_PROBABILITY=0.95
```

These settings classify research reports only. They do not alter inference, execution plans, active-model activation or risk.

## Compatibility

- No active-model retraining is required.
- Backtests executed before 1.18.0 are not reconstructed.
- One family must represent genuinely comparable alternatives on an identical final-test timestamp grid.
- A hard-killed process may leave an open `STARTED` trial; the report remains blocked until the attempt is explicitly resolved rather than silently omitted.

## Verification

- Baseline: `540 passed, 4 skipped`.
- Post-change: `550 passed, 4 skipped`.
- Ruff, compileall, dependency check, frontend syntax and Alembic single-head checks passed in an isolated project environment.
- PostgreSQL integration tests remained skipped because no isolated `TEST_DATABASE_URL` was supplied.
