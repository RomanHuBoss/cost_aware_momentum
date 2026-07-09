# PATCH 1.52.20 — locked-orderbook-validation

Date: 2026-07-09

## Scope

Fail-closed hardening for orderbook/liquidity validation before Bybit depth snapshots can feed VWAP sizing, liquidity caps, execution evidence, or recommendation economics.

## Confirmed defect

`app.risk.liquidity.validate_orderbook_levels()` rejected crossed books where `best_ask < best_bid`, but accepted locked top-of-book snapshots where `best_ask == best_bid`.

A locked top-of-book is not a safe executable market-data state for this advisory system. Accepting it can create a zero-spread execution snapshot, understate execution friction, and make downstream liquidity/economics evidence look more favorable than a fail-closed market-data gate should allow.

## Fix

- Changed the top-of-book invariant from `best_ask < best_bid` to `best_ask <= best_bid`.
- Updated the diagnostic from `orderbook is crossed` to `orderbook is locked or crossed`.
- Added a regression in `tests/unit/test_orderbook_execution_quality_2026_07_05.py` proving that locked Bybit orderbook snapshots are rejected during normalization.

## Compatibility

- No Alembic migration.
- No `.env` variable changes.
- No public API schema changes.
- No order placement, amendment, cancellation, or withdrawal capability added.
- PostgreSQL-only and advisory-only invariants are unchanged.

## Verification

Red command before fix:

```bash
python -m pytest -q tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book
```

Red result:

```text
FAILED tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book - Failed: DID NOT RAISE <class 'ValueError'>
```

Green commands after fix:

```bash
python -m pytest -q \
  tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_rejects_locked_top_of_book \
  tests/unit/test_orderbook_execution_quality_2026_07_05.py::test_orderbook_normalization_uses_matching_engine_time_and_rejects_crossed_book
```

```text
2 passed in 0.79s
```

Related orderbook subset:

```bash
python -m pytest -q tests/unit/test_orderbook_execution_quality_2026_07_05.py tests/unit/test_orderbook_vwap_sizing_integrity_2026_07_08.py
```

```text
19 passed in 2.64s
```
