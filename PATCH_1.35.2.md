# Patch 1.35.2 — latest-prior point-in-time ticker selection

Date: 2026-07-06

## Problem

Signal publication, execution-plan construction and recommendation API/acceptance each implemented their own ticker query. Every query selected the absolute latest `TickerSnapshot` by descending `source_time` and only afterwards applied the future/stale check.

If a future-dated row existed because of clock rollback, legacy import, manual correction or inconsistent runtime time, it masked an older row that was already received and still within the configured freshness window. The selected future row then failed closed. The failure mode suppressed signal publication, blocked plan creation/acceptance and could make the system appear to produce very few recommendations even though usable prior market data existed.

## Correction

- Added `app/services/market_snapshots.py` as the shared ticker-selection contract.
- A ticker row is eligible only when both `source_time <= cutoff` and `received_at <= cutoff`.
- Filtering occurs before ordering.
- Ties are deterministic: `source_time DESC`, `received_at DESC`, `id DESC`.
- Signal publication and execution planning pass their exact `now` decision cutoff.
- Recommendation list/detail/acceptance paths use a stable request cutoff.
- Existing maximum-age/future-time checks remain in place after lookup.
- Empty symbol and timezone-naive cutoff values fail closed.

## Compatibility

- Database migration: none.
- New `.env` variables: none.
- Model artifact, feature, label, probability and policy schemas: unchanged.
- Risk, EV/RR and activation thresholds: unchanged.
- API response schema: unchanged.
- Advisory-only and read-only Bybit boundaries: unchanged.

## Validation

Baseline 1.35.1:

- `704 passed, 7 skipped, 62 warnings`;
- Ruff, compileall, pip check, JavaScript syntax and Alembic head passed.

Red evidence:

- the three new signal/execution/API cases failed with `TypeError: ... got an unexpected keyword argument 'cutoff'`;
- the original SQL contained neither source-time nor receipt-time cutoff predicates.

Release 1.35.2:

- `709 passed, 7 skipped, 62 warnings`;
- 70 focused signal/execution/API tests passed;
- Ruff, compileall, pip check, JavaScript syntax and Alembic head `0016_universe_replay_asof` passed.

PostgreSQL integration tests were skipped because no isolated `TEST_DATABASE_URL` was available.

## Operator action

Replace the application and restart API/inference worker processes. No migration, `.env` change or model retraining is required. Existing ticker rows are not rewritten; lookup semantics change immediately after restart.
