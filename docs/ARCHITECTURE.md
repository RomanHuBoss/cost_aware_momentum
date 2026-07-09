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
