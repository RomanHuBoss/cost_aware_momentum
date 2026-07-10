# Architecture

The system is a PostgreSQL-only, human-in-the-loop advisory platform for Bybit linear USDT perpetuals. It separates FastAPI/UI, market-data and inference workers, background training, PostgreSQL state storage, and research/maintenance CLI processes.

## Major data flow

1. Read-only Bybit market/account data is ingested into PostgreSQL.
2. Workers build point-in-time market features from confirmed candles, ticker/funding snapshots, instrument specs, and orderbook evidence.
3. Model runtime produces directional TP/SL/TIMEOUT probabilities for LONG and SHORT market scenarios.
4. Market-signal policy selects a direction and immutable signal geometry independent of a specific capital profile.
5. Execution-plan sizing applies the active capital profile, account state, liquidity, margin, instrument constraints, costs, and risk caps.
6. Operator actions accept/reject advisory plans; the project does not place, amend, cancel, or withdraw exchange orders.
7. Manual trade lifecycle records operator-entered fills and outcomes for accounting and diagnostics.

## Invariants

- Advisory-only: no live order execution endpoints are implemented.
- PostgreSQL-only: SQLite fallback is not supported.
- Fail-closed: stale, missing, invalid, or unverifiable market/account/model/risk evidence blocks publication or acceptance.
- Signal/plan separation: capital affects sizing and executability, not model direction or signal geometry.
- Model lifecycle: candidate artifacts are immutable, hash-bound, compared against incumbent evidence, and activated through guarded audit paths.

## 1.52.13 note

Exchange notional/maxQty caps are now distinct execution-risk constraints in sizing diagnostics. They are not treated as minimum-order failures.

## 1.52.23 ticker quote integrity note

Ticker-derived execution evidence uses one shared strict top-of-book invariant: bid and ask must be positive, finite, and `ask > bid`. Locked or crossed quotes are excluded from dynamic-universe eligibility; ticker ingestion retains a valid last price but stores no executable bid/ask; signal selection, plan construction, acceptance revalidation, entry-state rendering, and spread diagnostics fail closed through the shared validator.

## 1.52.24 operator surface boundary

The browser/operator data plane is private by default. Capital profiles, recommendations, trade journal, portfolio risk, detailed readiness/status, and the outbox SSE stream depend on `current_operator`; state-changing routes, including logout, depend on `require_csrf`. Authentication accepts either a signed same-site session cookie or the explicit `X-Operator-Token` machine credential. `/health/live` remains the only anonymous health probe and exposes no database, migration, model, worker, trainer, account, signal, or audit details.
