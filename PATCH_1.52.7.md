# Patch 1.52.7 — open-interest backfill depth and stale-hourly suppression

Date: 2026-07-08

## Problem

User logs showed two independent fail-closed waits:

1. Repeated `Hourly decision cycle skipped because publication window is stale` for the same event hour after `publication_lag_seconds > MAX_SIGNAL_PUBLICATION_DELAY_SECONDS`.
2. Trainer defer `insufficient_walk_forward_history_after_filtering` with `actual_timestamps=326` and `required_timestamps=366`.

The second issue was traced to progressive open-interest history depth, not to the candle startup depth fixed in 1.52.6. Candles can request 1500+ rows, but hourly open-interest history is capped at 200 rows per page and the generic default `HISTORY_BACKFILL_PAGES_PER_SYMBOL=2` provided only about 400 raw hourly OI rows. After point-in-time context, feature warm-up, label horizon, final holdout and purged walk-forward filtering, this produced about 326 usable development timestamps.

## Solution

- Added `HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL=7` as a separate setting.
- `history_backfill_job()` now uses this setting only for `sync_open_interest_history()`.
- `/api/v1/status` exposes `history_backfill.open_interest_pages_per_symbol`.
- Added a worker-level stale-hourly latch: after the first terminal stale skip for a given event hour, the loop suppresses repeated attempts until the next event hour.
- Added regression tests for both defects.

## Compatibility

- No database migration.
- No API-breaking change.
- No model artifact schema change.
- No order placement/update/cancel capability added.
- No temporal split, holdout, walk-forward, quality, policy or activation gate was weakened.

Existing `.env` files may add:

```env
HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL=7
```

If absent, the default is already 7. If explicitly set below 7, startup training may again wait for more OI history.

## Verification

Red on 1.52.6 with new tests:

```text
2 failed
AttributeError: 'Settings' object has no attribute 'history_backfill_open_interest_pages_per_symbol'
AttributeError: type object 'Worker' has no attribute 'hourly_decision_cycle_if_due'
```

Post-change:

```text
python -m pytest -q tests/unit/test_initial_training_backfill_readiness_2026_07_08.py tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py
7 passed
```

Chunked full unit suite:

```text
863 passed
```

Integration PostgreSQL tests were not run against a live database in the sandbox; `tests/integration_postgres` skipped because safe test DB was not configured.

## Operator notes

- Restart worker and trainer.
- Keep `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS` unchanged unless you intentionally want a different freshness contract. Stale signals remain blocked.
- For logs with `actual_timestamps=326, required_timestamps=366`, inspect `history_backfill.open_interest_history.progress` and ensure OI pages are not overridden below 7.
