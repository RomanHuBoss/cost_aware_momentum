# QA Report

Release: **1.35.2**

Date: **2026-07-06**
Scope: **latest-prior point-in-time ticker selection**

## Environment

- Python: 3.13.5 in the same isolated virtual environment used for baseline and post-checks.
- Project requirement: Python >=3.12.
- Node syntax check: available.
- Separate PostgreSQL integration database: not configured.
- Input archive: `cost_aware_momentum-1.35.1-timeout-current-entry-repricing.zip`.
- Input archive SHA-256: `fa119cdfae6432bac3a3bfa0de2c2affc9997cc735fa2f5e690cbee8b157435c`.
- Source version: 1.35.1.

## Baseline before changes

| Check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 704 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |

The seven skipped tests require an isolated PostgreSQL integration database.

## Confirmed defect

`app/services/signals.py::_latest_ticker`, `app/services/execution.py::latest_ticker` and `app/api/v1/recommendations.py::latest_ticker` independently selected the absolute latest row using only `ORDER BY source_time DESC LIMIT 1`.

The caller then rejected a future timestamp. This ordering was fail-closed but not latest-prior: a future row could mask a previous row that satisfied the decision cutoff and remained within `MAX_TICKER_AGE_SECONDS`.

Impact: hourly signal publication could record `stale_ticker`, execution plans could become `BLOCKED_STALE_DATA`, and acceptance could report a future ticker even when a valid prior quote existed. Severity: **high operational/point-in-time correctness defect**. It can suppress recommendations but does not by itself prove the cause of past trading losses.

Existing tests checked freshness after selection. They did not verify that database ordering first excludes rows unavailable at the decision/request cutoff.

## Red evidence

Command:

```bash
python -m pytest -q tests/unit/test_point_in_time_ticker_selection_2026_07_06.py
```

Before implementation all three consumers failed for the expected missing contract:

```text
TypeError: _latest_ticker() got an unexpected keyword argument 'cutoff'
TypeError: latest_ticker() got an unexpected keyword argument 'cutoff'
```

Result: **3 failed**.

The independent fake session returned the older valid row only when the SQL contained both point-in-time predicates. The old queries would select the future row.

## Implemented correction

- Added shared `app/services/market_snapshots.py`.
- Require a timezone-aware cutoff and non-empty normalized symbol.
- Filter by both `TickerSnapshot.source_time <= cutoff` and `TickerSnapshot.received_at <= cutoff`.
- Order eligible rows by source time, receipt time and row id descending.
- Propagate the same request/decision cutoff through signal, execution and recommendation paths.
- Preserve the existing maximum-age and future-time checks after selection.
- Do not rewrite historical rows or silently substitute fabricated values.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 709 passed, 7 skipped, 62 warnings |
| focused ticker/signal/execution/API suite | PASSED: 70 passed |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |

## Not run / residual limitations

- PostgreSQL integration tests and `manage.py test --require-integration`: NOT RUN because no isolated `TEST_DATABASE_URL` was available.
- `manage.py doctor`: NOT RUN because this sandbox does not contain the operator's configured PostgreSQL/Bybit runtime.
- Real PostgreSQL query-plan and index performance: NOT RUN.
- Actual forward effect on recommendation density: NOT RUN; requires production/shadow observation.
- The analogous `latest_orderbook` path still selects the absolute latest row and is intentionally outside this ticker-only iteration.
- This correction does not establish profitability, alter model gates or explain every past loss.
