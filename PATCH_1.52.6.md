# PATCH 1.52.6 — startup training backfill readiness

## Problem

The default training quality-gate preflight requires at least 1206 label-eligible hourly timestamps for the current default horizon, holdout span and walk-forward contract. The project default `INITIAL_BACKFILL_BARS` was only 1000, so a clean install could complete the startup market sync and still remain below the mathematically necessary training precondition.

There was a second implementation gap: `sync_candles()` accepted caller limits above 1000, but `BybitClient.get_kline()` clamps a single request to 1000 rows. Therefore simply raising `INITIAL_BACKFILL_BARS` would not have been sufficient; the startup path needed pagination.

## Change

- Increased default `INITIAL_BACKFILL_BARS` from 1000 to 1500.
- Updated `.env.example` to match the new default.
- Added `BYBIT_KLINE_PAGE_LIMIT=1000` and pagination inside `app.services.market_data.sync_candles()`.
- The pagination walks backward through `end_ms`, deduplicates open times and preserves existing fail-closed behavior for partial/failed symbol requests.
- Added regression tests for:
  - default startup backfill depth covering the current training quality-gate precondition;
  - a 1206-bar request producing two kline pages and 1206 distinct stored candle rows.

## Compatibility

- Database migrations: not required.
- `.env`: no new variables. Existing `INITIAL_BACKFILL_BARS=1000` remains accepted but is no longer the recommended value.
- API contract: unchanged.
- Model artifact schema: unchanged.
- Quality, holdout, walk-forward, policy, experiment-promotion and risk thresholds are unchanged.

## Verification

Red on unchanged 1.52.5 after adding the new tests:

```bash
python -m pytest -q tests/unit/test_initial_training_backfill_readiness_2026_07_08.py
```

Result: `2 failed`.

Substantial failures:

```text
E       AssertionError: assert 1000 >= 1206
E       assert 1000 == 1206
```

Green after fix:

```bash
python -m pytest -q tests/unit/test_initial_training_backfill_readiness_2026_07_08.py
```

Result: `2 passed`.

Targeted regression suite:

```bash
python -m pytest -q \
  tests/unit/test_initial_training_backfill_readiness_2026_07_08.py \
  tests/unit/test_historical_dynamic_bootstrap_2026_07_07.py \
  tests/unit/test_walk_forward_validation_2026_07_05.py \
  tests/unit/test_hourly_candle_retry_2026_07_04.py \
  tests/unit/test_candle_availability_integrity_2026_07_03.py
```

Result: `20 passed`.

Full unit suite post-check: `861 passed, 8 skipped in 27.79s`. Full available post-check status is documented in `docs/QA_REPORT.md`.

## Limitations

This patch makes the startup backfill capable of reaching the existing default training precondition quickly when the exchange has enough historical data and the active universe is not rate-limit constrained. It does not claim that the trained model is profitable, that quality gates will pass, or that experiment promotion evidence will become READY without paper/shadow/forward observations.
