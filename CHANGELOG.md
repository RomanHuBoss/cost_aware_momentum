# Changelog

## 1.52.19 — 2026-07-09

Scope: `mark-index-kline-volume`.

- Fixed `app.services.market_data._candle_values()` to treat Bybit `mark` and `index` kline payloads as price-only series when the exchange returns the documented five fields: startTime/open/high/low/close.
- Preserved fail-closed last-trade candle semantics: ordinary `last` kline still requires non-negative `volume` and `turnover`; malformed or incomplete last-trade rows still block persistence.
- Added red→green regressions for five-field mark/index klines and last-trade missing-volume rejection.
- No Alembic migration, `.env`, public API schema, or advisory-only/exchange endpoint changes.

# CHANGELOG

## 1.52.18 — 2026-07-09

Scope: `candle-ohlcv-validation`

- Hardened Bybit kline/OHLCV row normalization so open/high/low/close must be positive finite decimals, volume/turnover must be non-negative finite decimals, and OHLC geometry must be internally consistent before persistence.
- `sync_candles()` now reports malformed candle payloads as failed requests and does not call candle upsert for invalid OHLCV rows.
- Added regression coverage for invalid OHLC geometry, negative volume, non-finite turnover, and sync diagnostics/no-persistence behavior.
- No migration, `.env`, API schema, advisory-only, or Bybit endpoint changes.

## 1.52.17 — 2026-07-09

Scope: `wallet-account-contract`

- Hardened read-only Bybit wallet-balance parsing so missing, null, or non-list `result.list` payloads fail closed before downstream account sync.
- Added account wallet semantic validation: exactly one account row, required `coin` array, and required USDT coin row before persisting equity snapshots.
- Added client and account-sync regressions for malformed wallet payloads and partial wallet account rows.
- No migration, `.env`, API schema, advisory-only, or Bybit endpoint changes.

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
