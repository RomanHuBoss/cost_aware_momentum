# PATCH 1.52.17 — wallet-account-contract

Date: 2026-07-09  
Type: patch  
Scope: `wallet-account-contract`

## Summary

This patch hardens the Bybit read-only wallet/account path. `wallet-balance.result.list` now uses the same fail-closed list-shape validation as the other list-shaped Bybit endpoints, and account sync refuses to persist capital snapshots from partial wallet payloads.

## Fixed

- `BybitClient.get_wallet_balance()` now rejects missing, null, or non-list `result.list` payloads instead of returning malformed result dictionaries to downstream account code.
- `sync_read_only_account()` now validates that the wallet response contains exactly one account row.
- `sync_read_only_account()` now rejects account rows without a `coin` JSON array.
- `sync_read_only_account()` now rejects wallet payloads without a USDT coin row before fetching positions or writing account snapshots.

## Tests

- Extended `tests/unit/test_bybit_response_contract_2026_07_09.py` to cover wallet-balance list-shape validation.
- Added account sync regressions for missing wallet coin arrays and missing USDT coin rows.
- Updated existing account sync fixtures to include valid USDT coin evidence.

## Compatibility

- No database migration.
- No `.env` variable changes.
- No public API schema changes.
- No autonomous order placement, amendment, cancellation, or withdrawal capability added.
