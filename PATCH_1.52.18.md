# PATCH 1.52.18 — candle-ohlcv-validation

Date: 2026-07-09
Scope: `candle-ohlcv-validation`
Version type: patch

## Summary

This patch hardens Bybit kline/OHLCV persistence. Candle rows are now semantically validated before they can become persisted market facts:

- open/high/low/close must be positive finite `Decimal` values;
- volume and turnover must be non-negative finite `Decimal` values;
- OHLC geometry must be internally consistent: high cannot be below open/low/close and low cannot be above open/high/close;
- incomplete rows or invalid open timestamps fail closed;
- `sync_candles()` counts malformed candle payloads as failed requests and does not call candle upsert for invalid rows.

## Confirmed defect

Type: CONFIRMED DEFECT
Severity: high
Files: `app/services/market_data.py`, `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py`

Before this patch, `_candle_values()` converted kline prices using permissive Decimal parsing and defaulted missing volume/turnover to zero. A row with inconsistent OHLC geometry, negative volume, or non-finite turnover could be accepted into the persistence path. That violates fail-closed market-data semantics and can contaminate features, labels, inference freshness, and backtest evidence with impossible market facts.

## Fix

- Added `_required_candle_decimal()` and `_validated_candle_ohlcv()`.
- Replaced permissive `_decimal()` candle parsing with strict semantic validation.
- Updated `sync_candles()` so validation/upsert errors are reported through request diagnostics instead of being counted as successful candle persistence.

## Tests

New/extended regression coverage:

- `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_invalid_ohlcv_rows_before_persistence`
- `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_sync_candles_reports_malformed_ohlcv_without_persisting`

## Compatibility

- Database migration: not required.
- Alembic head unchanged: `0018_inference_observations`.
- `.env.example`: unchanged.
- Public API schema: unchanged.
- Bybit endpoint set: unchanged.
- Advisory-only invariant preserved; no order create/amend/cancel/withdraw capability added.
