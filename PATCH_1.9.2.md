# Patch 1.9.2 — exact hourly decision candle

## Problem

`publish_hourly_signals` accepted any latest candle younger than `MAX_CANDLE_AGE_SECONDS` (default 4200 seconds). Immediately after an hourly boundary, the previous candle was 3600 seconds old and therefore passed. The resulting signal was keyed to the new `event_time`; when the correct decision candle later arrived, the natural-key idempotency check prevented replacement.

## Resolution

- Require `latest_candle_close == event_time` before spread, funding, model-scenario and natural-key processing.
- Return `missing_decision_candle` for a recent but non-matching prior candle.
- Retain `stale_candle_cutoff` and `future_decision_candle` as diagnostic classifications.
- Add a regression test that proves scenario economics is never reached with previous-hour data.

## Compatibility

- Version: 1.9.2 patch release.
- Database migration: none; head remains `0009_candle_receipt_availability`.
- New `.env` variables: none.
- API/schema/artifact contracts: unchanged.
- Retraining: not required solely by this patch.

## Operator note

`missing_decision_candle` should be resolved by restoring/waiting for confirmed candle ingestion. Increasing `MAX_CANDLE_AGE_SECONDS` is not a valid workaround and no longer authorizes current-hour publication from an older close.

## Verification

See `docs/ITERATION_REPORT_2026-07-04_hourly-decision-candle-integrity.md` and `docs/QA_REPORT.md` for exact baseline, red/green and post-check results.
