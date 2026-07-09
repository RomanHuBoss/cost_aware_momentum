# Specification compliance

## Implemented and unit-tested

- Advisory-only Bybit client does not expose order create/amend/cancel/withdraw methods.
- Bybit list-shaped endpoint payloads for tickers, kline, fee-rate, wallet balance, instruments, funding history, open interest, and positions are fail-closed validated for present, non-null JSON arrays before downstream use.
- Bybit ordinary `last` kline rows are semantically validated before persistence: open/high/low/close must be positive finite decimals, volume/turnover must be non-negative finite decimals, and OHLC geometry must be internally consistent.
- Bybit `mark` and `index` kline rows are handled as documented price-only candles when volume/turnover are absent; OHLC validation remains strict and shared non-null `market.candles` volume/turnover columns receive explicit zero placeholders only when both fields are absent. Partial OHLCV-like mark/index rows with one optional field missing fail closed before persistence.
- Malformed ordinary candle rows are reported as failed candle requests and are not persisted as market facts.
- Orderbook normalization rejects empty, malformed, duplicate, unsorted, locked, and crossed top-of-book levels before snapshots can feed VWAP sizing or execution evidence.
- PostgreSQL-only settings validation rejects SQLite database URLs.
- Risk sizing floors quantity to step and blocks unsafe min-size cases instead of rounding up.
- LONG/SHORT geometry validation rejects inverted TP/SL relationships.
- Funding sign is trader-perspective correct in risk math.
- Funding cash-flow rejects non-positive/non-finite position notional before applying LONG/SHORT funding sign.
- Execution fee cash rejects invalid execution price and negative/non-finite fee rates before fee arithmetic.
- Wallet/account sync validates exactly one Bybit UNIFIED account row, required account `coin` array, and a USDT coin row before persisting equity snapshots.
- Acceptance validator rechecks fresh entry zone, current funding deterioration, per-trade risk, total portfolio risk, margin, liquidity, and economics.
- `BLOCKED_EXCHANGE` distinguishes exchange-cap constraints from min-order constraints.

## Implemented but requires configured environment for full verification

- Alembic migrations and PostgreSQL integration paths.
- End-to-end API, worker, trainer, and database workflows.
- Model activation and drift-monitoring paths that require database-backed state.

## Not claimed by this release

- Live profitability.
- Autonomous order execution.
- Complete validation of every research/model/econometric path in this sandbox environment.

## Current verification limitations

The sandbox lacks `psycopg` and `ruff`; therefore full pytest collection and ruff static analysis cannot be completed here. PostgreSQL integration tests and `manage.py doctor` were not run because no safe PostgreSQL test configuration was provided. The sandbox-wide `moviepy`/`pillow` dependency conflict also prevents a clean `python -m pip check` result.
