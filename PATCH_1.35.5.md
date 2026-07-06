# Patch 1.35.5 — decision-time ticker freshness barrier

Date: 2026-07-07

## Problem

The worker refreshed general market data before potentially long orderbook, newly-admitted-symbol backfill, outcome and drift work. Hourly inference and universe catch-up inference did not refresh tickers themselves. With `MAX_TICKER_AGE_SECONDS=120`, any cycle delayed by more than two minutes could therefore reach `publish_hourly_signals` with every active symbol stale. The supplied log shows exactly this synchronized failure across BTCUSDT, ETHUSDT, SOLUSDT and the rest of the universe.

Normal `market_job` also wrote the ticker payload before slow orderbook/backfill operations and only then reported the job complete. The structured formatter discarded ticker age/timestamps, obscuring the cause.

## Correction

- Added a shared active-universe ticker refresh contract.
- Every actual hourly inference attempt fetches and persists a fresh public Bybit all-tickers payload in the same transaction immediately before signal publication.
- Universe catch-up inference uses the same barrier.
- A zero-row refresh for a non-empty active universe fails before publication.
- Normal market sync performs slow work first, then obtains and stores a separate final ticker response.
- Partial coverage is exposed in `JobRun.details` and warning logs.
- Stale warnings include actual age, configured maximum, source time and receipt time.

## Compatibility

- Database migration: none.
- New `.env` variables: none.
- Model artifact, feature, label, probability and policy schemas: unchanged.
- API/UI contracts: unchanged.
- `MAX_TICKER_AGE_SECONDS`, quality gates, activation gates, EV/RR thresholds, leverage and risk limits are unchanged.
- Advisory-only and read-only Bybit boundaries are unchanged.

## Validation

Baseline 1.35.4:

- `725 passed, 7 skipped, 62 warnings`;
- pip check, Ruff, compileall, JavaScript syntax and Alembic head passed in an isolated environment.

Red evidence:

- four refresh/order tests failed against 1.35.4;
- the logging test failed because `ticker_age_seconds` was absent from serialized JSON.

Release 1.35.5:

- `730 passed, 7 skipped, 62 warnings`;
- five new regression tests pass;
- focused affected suite passed;
- pip check, Ruff, compileall, JavaScript syntax and Alembic head `0016_universe_replay_asof` pass.

PostgreSQL integration was not run because no isolated `TEST_DATABASE_URL` was available.

## Operator action

Replace the application and restart the inference worker. No migration, `.env` change or active-model retraining is required. After restart, inspect `hourly_inference` JobRun details under `decision_ticker_refresh`; any remaining stale warning now includes exact age and timestamps. Do not increase `MAX_TICKER_AGE_SECONDS` to hide a failed refresh.
