# Specification compliance

## Implemented and unit-tested

- Operator authentication protects capital profiles, recommendations/details, manual trades, portfolio risk, detailed readiness/status, and the SSE outbox stream.
- State-changing operator routes use authenticated CSRF; logout is included in that contract.
- Production settings reject `COOKIE_SECURE=false`; local non-production HTTP remains configurable.
- `/health/live` is intentionally anonymous and minimal. Login, static UI, static glossary, and the public market chart are outside the private operator-data boundary.
- Ticker top-of-book evidence is fail-closed across ingestion, dynamic-universe selection, market-signal policy, plan construction, acceptance revalidation, entry-state rendering, and spread diagnostics: bid/ask must be positive, finite, and strictly unlocked (`ask > bid`).
- Frontend recommendation detail data lists escape labels and values before `innerHTML` insertion.
- Advisory-only Bybit client does not expose order create/amend/cancel/withdraw methods.
- Bybit list-shaped endpoint payloads and ordinary/mark/index kline shapes are validated fail-closed before persistence or use.
- Orderbook normalization rejects empty, malformed, duplicate, unsorted, locked, and crossed top-of-book levels.
- PostgreSQL-only settings validation rejects SQLite database URLs.
- Risk sizing floors quantity to step and blocks unsafe min-size cases instead of rounding up.
- LONG/SHORT geometry, funding sign, fee cash, wallet/account sync, acceptance revalidation, and exchange-cap classification retain existing tested contracts.

## Implemented but requires configured environment for full verification

- Alembic upgrade/downgrade and PostgreSQL integration/concurrency paths.
- End-to-end API, worker, trainer, and database workflows under a real reverse proxy/TLS deployment.
- Machine readiness-probe configuration using a deployment-owned `OPERATOR_API_TOKEN`.
- Browser `EventSource` reconnect behavior through the deployment proxy after session expiration/re-authentication.

## Not claimed by this release

- Live profitability or autonomous order execution.
- Complete validation of every research/model/econometric path.
- Penetration testing of the surrounding host, reverse proxy, TLS termination, or browser environment.

## Current verification limitations

A clean isolated virtual environment completed dependency, compile, Ruff, JavaScript syntax, Alembic-head, and the full non-integration pytest suite. PostgreSQL integration tests and `manage.py doctor` were not run because no safe `TEST_DATABASE_URL` or local deployment database was available. Host-Python dependency failures were recorded separately and were not used as release evidence. Real TLS/session-cookie transport and real proxy health probes were not exercised.
