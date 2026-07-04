# Patch 1.9.4 — bounded hourly decision-candle refetch

## Problem

`hourly_market_close` used the generic job runner and called `sync_candles`, which deliberately caught per-symbol Bybit errors so that one timeout would not abort all successful inserts. The task nevertheless returned normally and the job was stored as `SUCCESS`.

On the next worker loop, the same hourly job was skipped as already completed. `hourly_inference` could retry its database query, but no process fetched the missing candle again: regular minute market sync refreshes tickers and only backfills candles for newly admitted symbols. A transient timeout or an API response without the exact close therefore suppressed that symbol for the rest of the hour.

This is a confirmed high-severity availability/correctness defect. It explains one source of rare recommendations, but source code alone cannot attribute historical losses or all `NO_TRADE` decisions to it.

## Resolution

- `sync_candles` optionally accepts a timezone-aware `required_close_time` and reports:
  - total and exactly covered symbols;
  - total/succeeded/failed read-only requests;
  - required close timestamp;
  - a bounded sample of missing symbols.
- Coverage counts only a confirmed `last` candle whose `close_time` exactly equals the hourly decision timestamp. Mark/index rows cannot satisfy it.
- The generic job retry predicate now supports explicit total/covered/retry-count keys while preserving the existing inference wrapper.
- `hourly_market_close` is retryable after cooldown when exact coverage is partial, performs a real Bybit refetch and stops after five retries or complete coverage.
- Existing exact-candle, feature, model-quality, EV/RR, risk and acceptance gates remain unchanged.

## Compatibility

- Version: 1.9.4 patch release.
- Database migration: none; Alembic head remains `0009_candle_receipt_availability`.
- New `.env` variables: none.
- Dependencies/public HTTP API/model artifact schema: unchanged.
- Advisory-only and Bybit read-only boundaries: unchanged.

## Operator action

Replace the project files and restart the worker/API/trainer. Inspect `hourly_market_close` job details for `symbols_total`, `symbols_covered`, `requests_failed`, `missing_symbols_sample` and `candle_sync_retry_count`. Do not weaken `missing_decision_candle` or economic gates to force recommendations.

## Verification

See `docs/ITERATION_REPORT_2026-07-04_hourly-candle-retry.md` and `docs/QA_REPORT.md` for baseline, red/green and post-check evidence.
