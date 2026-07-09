# PATCH 1.52.19 — mark-index-kline-volume

Date: 2026-07-09
Scope: `mark-index-kline-volume`
Version type: patch

## Summary

This patch fixes a production-visible Bybit kline ingestion defect: mark-price and index-price klines are documented as price-only arrays, but the previous release applied ordinary last-trade OHLCV validation to every `price_type`. Live sync with `price_types=("last", "mark", "index")` could therefore count valid mark/index rows as validation failures with `missing kline.volume`.

## Confirmed defect

Type: CONFIRMED DEFECT
Severity: high
Files: `app/services/market_data.py`, `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py`

- Actual behavior: `_candle_values()` required `row[5]` volume and `row[6]` turnover for `last`, `mark`, and `index` price types.
- Expected behavior: `last` klines remain full OHLCV rows, while `mark` and `index` klines accept the documented price-only shape without treating absent volume/turnover as malformed market data.
- Impact: valid mark/index candle responses could be logged as `candle_validation_failed`, counted as failed requests, and left missing from the database; downstream model context can then lose mark/index basis evidence and degrade into stale/missing-data gates.

## Fix

- `_validated_candle_ohlcv()` is now price-type-aware.
- For `price_type="last"`, volume and turnover remain mandatory, finite, and non-negative.
- For `price_type="mark"` and `price_type="index"`, missing volume/turnover are persisted as explicit `Decimal("0")` placeholders because the shared `market.candles` table has non-null OHLCV columns, while OHLC price validation remains strict.
- Optional extra volume/turnover fields on mark/index rows, if present, are still validated as finite non-negative decimals.

## Tests

New/extended regression coverage:

- `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover`
- `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_still_reject_last_klines_missing_volume_turnover`

Red evidence before implementation:

```text
FAILED tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover
ValueError: Bybit kline row is incomplete: missing kline.volume
```

Green evidence after implementation:

```text
2 passed in 3.05s
```

Related subset after implementation:

```text
13 passed in 2.69s
```

## Compatibility

- Database migration: not required.
- Alembic head unchanged: `0018_inference_observations`.
- `.env.example`: unchanged.
- Public API schema: unchanged.
- Bybit endpoint set: unchanged; still public/read-only market data and read-only account endpoints only.
- Advisory-only invariant preserved; no order create/amend/cancel/withdraw capability added.
