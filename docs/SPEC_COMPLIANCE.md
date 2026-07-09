# Specification compliance

## Implemented and unit-tested

- Advisory-only Bybit client does not expose order create/amend/cancel/withdraw methods.
- PostgreSQL-only settings validation rejects SQLite database URLs.
- Risk sizing floors quantity to step and blocks unsafe min-size cases instead of rounding up.
- LONG/SHORT geometry validation rejects inverted TP/SL relationships.
- Funding sign is trader-perspective correct in risk math.
- Acceptance validator rechecks fresh entry zone, current funding deterioration, per-trade risk, total portfolio risk, margin, liquidity, and economics.
- `BLOCKED_EXCHANGE` now distinguishes exchange-cap constraints from min-order constraints.

## Implemented but requires configured environment for full verification

- Alembic migrations and PostgreSQL integration paths.
- End-to-end API, worker, trainer, and database workflows.
- Model activation and drift-monitoring paths that require database-backed state.

## Not claimed by this release

- Live profitability.
- Autonomous order execution.
- Complete validation of every research/model/econometric path in this sandbox environment.

## Current verification limitations

The sandbox lacks `psycopg` and `ruff`; therefore full pytest collection and ruff static analysis cannot be completed here. PostgreSQL integration tests and `manage.py doctor` were not run because no safe PostgreSQL test configuration was provided.
