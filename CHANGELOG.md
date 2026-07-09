# CHANGELOG

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
