# Patch 1.8.21 — linear perpetual product boundary

## Problem

On 2026-07-01 the worker repeatedly failed during `instrument_sync` with:

```text
ValueError: Bybit field fundingInterval must be a positive integer
```

The public Bybit `category=linear` response is not perpetual-only. It includes both `LinearPerpetual` and delivery-settled `LinearFutures`. A dated USDT future can legitimately expose `fundingInterval=0`; version 1.8.20 validated that row as though it were a perpetual before the dynamic-universe filter could exclude it. One out-of-scope contract therefore aborted the complete synchronization batch and the worker loop.

## Resolution

- `sync_instruments()` now excludes every non-`LinearPerpetual` row immediately after the USDT-settlement check.
- Strict positive `fundingInterval` validation remains in `_instrument_spec_values()` for in-scope perpetuals.
- No zero funding interval, synthetic interval or local default is persisted.
- Added a regression fixture with a `LinearFutures` row using `fundingInterval=0` followed by a valid `LinearPerpetual`; synchronization persists only the perpetual and returns count `1`.

## Compatibility

- Database migration: none.
- `.env` changes: none.
- API schema: unchanged.
- Advisory-only and PostgreSQL-only boundaries: unchanged.
- Rollback: stop the worker, restore 1.8.20 source, restart. No database downgrade is required; rollback reintroduces the worker-loop failure when a dated future is returned.

## Verification

- Red: the new regression failed on unchanged 1.8.20 with the same `ValueError` as the operator log.
- Green: 12 focused market-data/universe tests passed.
- `compileall` and `node --check web/js/app.js` passed.
- Full pytest collection was unavailable in the supplied sandbox because `psycopg` was not installed; PostgreSQL integration and live Bybit smoke were not claimed.
