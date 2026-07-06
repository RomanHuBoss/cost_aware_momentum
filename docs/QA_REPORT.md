# QA Report

Release: **1.35.5**

Date: **2026-07-07**
Scope: **decision-time ticker freshness and stale-data diagnostics**

## Environment

- Python: 3.13.5.
- Project requirement: Python >=3.12.
- Input archive: `cost_aware_momentum-main.zip`.
- Input SHA-256: `5da181879da5accfb397d9b6907257d7f00d51b56f105215b247ac2018b77df6`.
- Source version: 1.35.4.
- Separate PostgreSQL integration database: not configured.

The host-wide Python environment initially lacked project dependencies and had an unrelated MoviePy/Pillow conflict. A clean isolated virtual environment was created from `pyproject.toml`; the reproducible project baseline below was recorded there before production-code changes.

## Baseline

| Check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED in isolated project environment |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 725 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED: one head, `0016_universe_replay_asof` |

## Confirmed defect and red evidence

The worker performed general market polling before potentially long orderbook, candle-history, funding/OI, outcome and drift work. `hourly_inference` and `universe_catchup_inference` then published against whatever ticker row happened to remain in PostgreSQL. A cycle delayed longer than `MAX_TICKER_AGE_SECONDS=120` therefore skipped the whole universe with `stale_ticker`, matching the supplied simultaneous BTC/ETH/SOL/... warnings.

The original normal `market_job` also persisted the ticker payload before slow orderbook/backfill work, so `last_market_sync` could be advanced only after the just-written rows were already stale. The JSON formatter discarded the already-computed `ticker_age_seconds`, leaving the operator without the age and timestamp evidence.

Five new tests were run before the fix:

- four decision-refresh tests failed: inference and catch-up published without a fresh fetch, zero-row refresh did not block, and market-sync order was `fetch → persist → slow work`;
- the logging test failed with `KeyError: ticker_age_seconds` because freshness diagnostics were removed by the formatter.

## Implemented correction

- Shared `_refresh_tickers_for_symbols` performs a new public Bybit ticker GET, persists only the active set and returns bounded coverage diagnostics.
- Every actual hourly inference attempt refreshes tickers inside its own database transaction immediately before `publish_hourly_signals`.
- Universe catch-up inference uses the same barrier.
- A non-empty universe with zero persisted ticker rows raises before publication; stale-data gates remain fail-closed and are not widened.
- Normal market sync performs orderbook/new-symbol backfill first, then fetches a separate final ticker payload and persists it last.
- Structured logs retain ticker age, configured maximum, source time, receipt time and partial-refresh evidence.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 730 passed, 7 skipped, 62 warnings |
| focused affected suites | PASSED: 46 tests before final full suite; 5 new tests independently green |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |
| source release manifest | PASSED after cache cleanup and checksum regeneration; final ZIP validation is reported externally because its hash cannot be embedded without changing the archive |

## Compatibility and operator action

- PostgreSQL migration: none.
- New or changed `.env` variables: none.
- Model artifact, feature, label, probability and policy schemas: unchanged.
- Model quality, activation, EV/RR, leverage and risk thresholds: unchanged.
- Restart the inference worker after replacing the project. API/trainer restart is optional unless deployed together.

## Not run / residual limitations

- PostgreSQL integration tests and `manage.py test --require-integration`: not run because no isolated `TEST_DATABASE_URL` was supplied.
- `manage.py doctor` against the operator runtime: not run because the archive contains no configured PostgreSQL/Bybit environment.
- Real Bybit latency, partial all-tickers payloads and long-duration production worker behavior were not exercised.
- Orderbook refresh still occurs in the normal market job, not inside the final ticker-only inference barrier; plan construction remains fail-closed if orderbook evidence ages out.
- Candidate-gate diagnosis and realized-loss attribution remain unavailable without the operator database, artifacts, fills and outcome evidence.
- Profitability is not proven.
