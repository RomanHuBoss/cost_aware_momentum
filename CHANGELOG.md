# CHANGELOG

## 1.52.16 — 2026-07-09

Scope: `bybit-list-presence`

- Hardened read-only Bybit list extraction so missing or null `result.list` payloads fail closed instead of being silently converted to empty lists.
- Extended the contract from tickers/kline/fee-rate to all list-shaped Bybit client methods: instruments, funding history, open interest, and positions.
- Added async regression coverage for missing and null list payloads across public market-data and private read-only account endpoints.
- No migration, `.env`, API schema, advisory-only, or Bybit endpoint changes.

## 1.52.15 — 2026-07-09

Scope: `bybit-list-payload-validation`

- Hardened read-only Bybit list extraction for tickers, kline, and fee-rate responses so malformed non-list `result.list` payloads fail closed instead of propagating downstream.
- Added a pure async unit regression covering malformed list payloads across public market-data and private read-only account-cost endpoints.
- No migration, `.env`, API schema, advisory-only, or Bybit endpoint changes.

## 1.52.14 — 2026-07-09

Scope: `validated-cash-inputs`

- Hardened `funding_cash_flow()` so funding accounting rejects non-positive/non-finite `position_value` instead of allowing a negative notional to invert LONG/SHORT funding sign.
- Hardened `fee_cash()` so execution fee accounting rejects invalid execution prices and negative/non-finite fee rates instead of producing impossible negative fees.
- Added pure unit regression coverage for negative funding notional and negative fee-rate inputs.
- No migration, `.env`, API schema, advisory-only, or Bybit endpoint changes.

## 1.52.13 — 2026-07-09

### Fixed
- `calculate_position_plan()` now reports exchange notional/maxQty caps as `BLOCKED_EXCHANGE` with limiting cap `EXCHANGE` instead of collapsing those cases into `BLOCKED_MIN_SIZE`.
- Limited plans constrained by exchange caps now include an operator-visible warning that the position size is exchange-limited.
- Candidate/live attrition classifies `BLOCKED_EXCHANGE` as `RISK_EXECUTION`.
- Frontend status labels now display `BLOCKED_EXCHANGE` as a distinct exchange-limit state.

### Tests
- Added regression coverage for exchange-cap blocked and exchange-cap limited position plans.
- Added attrition evidence coverage for `BLOCKED_EXCHANGE`.

### Compatibility
- No database migration.
- No `.env` variable changes.
- No public API schema changes.
- No order placement, amendment, cancellation, or withdrawal capability added.
