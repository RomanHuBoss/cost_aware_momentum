# PATCH 1.52.21 — partial-mark-index-kline-validation

Date: 2026-07-09

## Scope

Fail-closed hardening for Bybit mark/index kline normalization before malformed partial OHLCV-like rows can be persisted as candle market facts.

## Confirmed defect

`app.services.market_data._validated_candle_ohlcv()` correctly accepted documented five-field Bybit mark/index price-only klines and populated the shared non-null `market.candles` volume/turnover columns with explicit zero placeholders. However, if an upstream mark/index row contained one optional OHLCV-like field (`volume`) but omitted the paired `turnover` field, the function accepted the exchange-provided volume and silently inserted synthetic zero turnover.

That mixed partially observed exchange data with a placeholder in a market-fact row. The advisory system should only use the synthetic zero placeholder when both mark/index volume and turnover are truly absent, or validate both fields when both are present.

## Fix

- Kept documented five-field mark/index price-only rows valid with explicit zero volume/turnover placeholders.
- Validated optional mark/index volume/turnover only when both fields are present.
- Rejected partial mark/index OHLCV-like rows fail-closed with an operator-readable validation message.
- Added a regression in `tests/unit/test_point_in_time_candle_integrity_2026_07_01.py` proving that partial mark/index rows do not pass `_candle_values()`.

## Compatibility

- No Alembic migration.
- No `.env` variable changes.
- No public API schema changes.
- No order placement, amendment, cancellation, or withdrawal capability added.
- PostgreSQL-only and advisory-only invariants are unchanged.

## Verification

Red command before fix:

```bash
python -m pytest -q tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows
```

Red result:

```text
FAILED tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows - Failed: DID NOT RAISE <class 'ValueError'>
1 failed in 2.98s
```

Green command after fix:

```bash
python -m pytest -q tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows
```

Green result:

```text
1 passed in 2.61s
```

Related candle subset:

```bash
python -m pytest -q \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_accept_mark_and_index_price_only_klines_without_volume_turnover \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_partial_mark_index_ohlcv_rows \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_still_reject_last_klines_missing_volume_turnover \
  tests/unit/test_point_in_time_candle_integrity_2026_07_01.py::test_candle_values_reject_invalid_ohlcv_rows_before_persistence
```

```text
4 passed in 2.62s
```
