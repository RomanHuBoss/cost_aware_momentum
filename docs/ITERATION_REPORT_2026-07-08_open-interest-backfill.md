# Iteration report — 2026-07-08 — open-interest backfill readiness

## 1. Input archive

- Input ZIP: `cost_aware_momentum-1.52.6-startup-training-backfill.zip`.
- SHA-256 input ZIP: `02733885af0bfe0ba22f14ed4534c237f6dd2b044a18b2a586d9ff7950641c0a`.
- Source version: 1.52.6.
- Alembic head: `0018_inference_observations`.

## 2. Goal and acceptance criteria

After this iteration, a clean/default worker history backfill must not cap point-in-time hourly open-interest context below the current training walk-forward/history precondition, and the worker must not repeatedly log the same stale hourly decision attempt for one event hour.

Acceptance criteria:

1. Default open-interest backfill capacity is at least the current 1206-hour training-readiness precondition.
2. Generic candle/funding history page count is not globally inflated just to satisfy OI.
3. `history_backfill_job()` uses the OI-specific page count for OI only.
4. Status diagnostics expose the OI-specific page count.
5. Repeated stale hourly cycles for the same event hour are suppressed after the first terminal skip.
6. The next event hour remains eligible for processing.
7. No ML/econometric gates, temporal split, holdout, walk-forward, activation gate, risk math or advisory-only boundary is weakened.

## 3. Read sources and data flow

Read: `README.md`, `CHANGELOG.md`, `PATCH_1.52.6.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/CONFIGURATION.md`, `docs/OPERATOR_MANUAL.md`, `app/config.py`, `app/services/market_data.py`, `app/workers/runner.py`, `app/api/v1/status.py`, `app/ml/training.py`, and related unit tests.

Data flow:

`worker history_backfill_job -> symbols_needing_open_interest_history_backfill -> sync_open_interest_history -> PostgreSQL OpenInterest -> build_market_context_frame -> make_barrier_dataset -> chronological_split -> _walk_forward_development_frame -> require_walk_forward_capacity -> trainer DEFERRED/fit`.

Stale decision flow:

`worker loop -> event_time/run_after -> hourly_decision_cycle_if_due -> hourly_decision_cycle -> publication-window guard -> terminal stale skip or normal jobs`.

## 4. Baseline before changes

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | ambient `moviepy` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | NOT RUN to completion | all-in-one run timed out in sandbox; post verification used deterministic chunks |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | NOT RUN | project-local `.venv` absent |
| `python manage.py test --require-integration` | NOT RUN | safe PostgreSQL `TEST_DATABASE_URL` not configured |

## 5. Confirmed defects/gaps

### CONFIRMED DEFECT — OI history depth prevents training readiness

- Severity: high operational/model-readiness.
- Evidence: user log showed `actual_timestamps=326`, `required_timestamps=366`, `reason_code=insufficient_walk_forward_history_after_filtering`.
- Code path: `app/workers/runner.py::history_backfill_job` passed generic `history_backfill_pages_per_symbol=2` into `sync_open_interest_history()`.
- Mechanism: open-interest requests are bounded to 200 rows/page in the client/service; 2 pages provide about 400 hourly rows, which shrink to about 326 usable development timestamps after point-in-time/context/label filtering.
- Expected: startup/progressive defaults should make the current training contract reachable without lowering walk-forward gates.
- Existing tests only covered candle kline pagination and initial candle depth, not OI depth.

### CONFIRMED DEFECT — repeated stale hourly skip for the same event hour

- Severity: medium operational/diagnostic noise.
- Evidence: user log showed repeated `Hourly decision cycle skipped because publication window is stale` for event_time `2026-07-08T03:00:00+00:00` at multiple loop iterations.
- Code path: `app/workers/runner.py::run` called `hourly_decision_cycle()` every loop after `run_after`; stale skip returned but was not latched.
- Expected: stale signal remains blocked, but the same terminal skip should not be reattempted until the next event hour.

## 6. Plan and actual diff

Production/config:

- `app/config.py` — added `history_backfill_open_interest_pages_per_symbol=7` and validation.
- `app/workers/runner.py` — OI history uses the OI-specific pages setting; stale hourly skips are latched by `hourly_decision_cycle_if_due()`.
- `app/api/v1/status.py` — exposes `history_backfill.open_interest_pages_per_symbol`.
- `app/__init__.py`, `pyproject.toml` — version 1.52.7.
- `.env.example` — documents new env variable.

Tests:

- `tests/unit/test_initial_training_backfill_readiness_2026_07_08.py` — new OI readiness contract test.
- `tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py` — new stale-hour suppression test.

Docs:

- `README.md`, `CHANGELOG.md`, `PATCH_1.52.7.md`, `docs/CONFIGURATION.md`, `docs/OPERATOR_MANUAL.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, this report.

Migrations: none.

## 7. Red → green evidence

Red on 1.52.6 with new tests copied in:

```bash
python -m pytest -q \
  tests/unit/test_initial_training_backfill_readiness_2026_07_08.py::test_default_open_interest_history_backfill_covers_training_quality_gate_precondition \
  tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py::test_repeated_stale_hourly_cycle_is_suppressed_until_next_event_hour
```

Result: `2 failed`.

Essential output:

```text
AttributeError: 'Settings' object has no attribute 'history_backfill_open_interest_pages_per_symbol'
AttributeError: type object 'Worker' has no attribute 'hourly_decision_cycle_if_due'
```

Green after fix:

```bash
python -m pytest -q \
  tests/unit/test_initial_training_backfill_readiness_2026_07_08.py \
  tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py
```

Result: `7 passed`.

## 8. Migrations, API/config/env compatibility

- Migrations: none.
- API breaking changes: none.
- Status API additive field: `history_backfill.open_interest_pages_per_symbol`.
- New env variable: `HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL=7`.
- Existing `.env` files are valid; absent value uses default 7.
- No order execution endpoint or Bybit private mutation was added.

## 9. Post-check

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED / environment limitation | ambient `moviepy`/`pillow` conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| targeted regression tests | PASSED | `7 passed` |
| chunked `python -m pytest -q tests/unit` | PASSED | `863 passed` across five chunks |
| `python -m pytest -q tests/integration_postgres` | SKIPPED | `8 skipped` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |

Chunk evidence:

```text
chunk 1: 168 passed
chunk 2: 200 passed
chunk 3: 155 passed
chunk 4: 202 passed
chunk 5: 138 passed
```

## 10. Not verified

- PostgreSQL integration tests against a real test database were not run; no safe `TEST_DATABASE_URL` was configured.
- `python manage.py doctor` was not run successfully because the sandbox lacks project-local `.venv`.
- Live Bybit/network smoke was not run and no credentials were used.
- Economic edge/profitability is not proven by this patch.

## 11. Residual risks and limitations

- If a local `.env` explicitly overrides `HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL` below 7, the same defer can recur.
- Very large dynamic universes still depend on `HISTORY_BACKFILL_SYMBOLS_PER_CYCLE`; OI depth is now sufficient per processed symbol, but the full universe may require multiple cycles.
- A candidate can still fail later quality/policy/econometric gates; this is correct fail-closed behavior.

## 12. Rollback procedure

1. Stop worker and trainer.
2. Restore previous 1.52.6 code/ZIP.
3. Remove `HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL` from `.env` if desired.
4. Restart worker/trainer.

Rollback risk: the trainer may again defer near `actual_timestamps≈326` if OI history remains capped by 2 pages.

## 13. Recommended next work package

Add operator-facing history-readiness diagnostics that decompose candidate training attrition by source: last/mark/index candles, open interest, funding, instrument specs, universe replay and label horizon. Do not implement this inside the current patch.
