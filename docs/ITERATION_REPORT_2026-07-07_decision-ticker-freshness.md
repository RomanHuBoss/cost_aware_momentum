# Iteration report: decision-time ticker freshness

Date: **2026-07-07**
Release: **1.35.5**

## 1. Input and baseline identity

- Input archive: `cost_aware_momentum-main.zip`.
- Input SHA-256: `5da181879da5accfb397d9b6907257d7f00d51b56f105215b247ac2018b77df6`.
- Actual source version: 1.35.4.
- Python requirement: >=3.12; tested with 3.13.5.
- Alembic head: `0016_universe_replay_asof`.
- Input counts: 101 production/web/script files, 99 test files, 12 documentation files, 16 migration revision files plus migration support files.
- No `.env`, virtual environment, model artifact, database dump or build directory was present in the input archive. The existing `SHA256SUMS` required regeneration after the patch.

## 2. Goal and acceptance criteria

After this iteration, every actual hourly or universe-catchup inference attempt must persist a newly fetched active-universe ticker batch immediately before signal publication, so long-running worker jobs cannot make the whole universe stale by construction.

Acceptance criteria:

1. hourly inference fetches and persists tickers before publication;
2. catch-up inference uses the same contract;
3. a zero-row refresh for a non-empty universe blocks before publication;
4. normal market sync writes a new ticker response after slow orderbook/backfill work;
5. stale warnings expose age, limit, source time and receipt time;
6. freshness limits and model/risk gates are unchanged;
7. full unit/static suite remains green.

## 3. Sources and data flow

Read: `README.md`, `CHANGELOG.md`, patches 1.35.1–1.35.3, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, release 1.35.4 audit/iteration report, `.env.example`, `pyproject.toml`, worker, market-data, signal, Bybit client, logging and related tests.

Affected flow before correction:

`Bybit /v5/market/tickers → market_job early insert → long orderbook/backfill/outcome/drift work → hourly inference → latest-prior DB lookup → stale skip`.

Affected flow after correction:

`long prerequisite work → fresh Bybit /v5/market/tickers → validation/persist in inference transaction → latest-prior lookup/freshness check → signal publication → JobRun diagnostics`.

## 4. Baseline

A host-global preflight failed because project dependencies were absent and an unrelated MoviePy/Pillow conflict existed. No code was changed. A clean isolated virtual environment was then installed from `pyproject.toml`, producing the reproducible baseline:

- `python --version`: Python 3.13.5, PASSED;
- `python -m pip check`: PASSED;
- `python -m compileall -q app scripts tests manage.py`: PASSED;
- `python -m ruff check .`: PASSED;
- `python -m pytest -q`: 725 passed, 7 skipped, 62 warnings, PASSED;
- `node --check web/js/app.js`: PASSED;
- `python -m alembic heads`: one head `0016_universe_replay_asof`, PASSED.

`manage.py doctor` and PostgreSQL integration were not run because no operator configuration or isolated test database was available.

## 5. Confirmed defects

### DEFECT-1 — inference depended on an earlier poll (high)

Files/functions: `app/workers/runner.py::market_job`, `inference_job`, `catchup_inference_job`, `hourly_decision_cycle`.

The inference jobs called `publish_hourly_signals` without obtaining current tickers. The worker is sequential and can spend longer than 120 seconds in orderbook, candle/funding/OI, outcome, drift or history work. The supplied log shows all symbols rejected together, which is the expected result when the shared last poll ages beyond the threshold.

Expected: every actual inference attempt establishes fresh market availability immediately before publication.
Actual: it trusted an earlier general poll.

Existing tests covered latest-prior lookup and stale rejection, but not the producer-to-consumer scheduling boundary.

### DEFECT-2 — market-sync completion could report already-aged ticker rows (high)

`market_job` fetched and inserted tickers before sequential orderbook and new-symbol backfill work. `last_market_sync` was updated only after all of that work completed. Thus the worker could consider a poll completed while its ticker rows were already stale.

Moving only the database insert would be unsafe because it would stamp an old payload with a new receipt time. The correction obtains a second, genuinely new response at the final boundary.

### DEFECT-3 — zero refresh remained silent (high)

A public response containing no valid active rows could still proceed to inference, which then generated a large series of stale/missing warnings. The new contract raises before publication when the active universe is non-empty and zero rows are stored.

### DEFECT-4 — freshness evidence was removed from JSON logs (medium)

`publish_hourly_signals` already computed `ticker_age_seconds`, but `JsonFormatter` serialized only a narrow key list. The operator log therefore showed the symbol but not the age or timestamps needed to distinguish worker delay, clock issues and ingestion failure.

## 6. Plan and actual diff

Production:

- `app/workers/runner.py`: shared refresh helper; inference/catch-up barrier; final market-sync response ordering.
- `app/services/signals.py`: complete stale-ticker diagnostic fields.
- `app/logging.py`: safe structured diagnostic allowlist.
- `app/__init__.py`, `pyproject.toml`: version 1.35.5.

Tests:

- `tests/unit/test_decision_ticker_refresh_2026_07_07.py`: five regressions.

Documentation:

- `README.md`, `CHANGELOG.md`, `PATCH_1.35.5.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this iteration report.

Migration/config/API: none.

## 7. Red → green evidence

Command: `python -m pytest -q tests/unit/test_decision_ticker_refresh_2026_07_07.py`.

Before correction:

- 4 failed: no refresh before hourly/catch-up publication, no zero-row block, wrong market-sync order;
- separate logging regression failed with `KeyError: ticker_age_seconds`.

After correction: `5 passed`.

The tests use independent event ordering and fail-closed assertions; they do not derive expectations from the implementation output.

## 8. Compatibility and rollback

- No migration.
- No `.env` change.
- No public API or browser schema change.
- No artifact/retraining requirement.
- No threshold change.
- Advisory-only/read-only boundary preserved.

Rollback: stop the worker, restore 1.35.4 code, restart the worker. Database rows written by 1.35.5 use the unchanged schema and remain readable. Rollback reintroduces the stale scheduling defect but does not require data rollback.

## 9. Post-check

- `python -m pip check`: PASSED;
- compileall: PASSED;
- Ruff: PASSED;
- full pytest: 730 passed, 7 skipped, 62 warnings;
- Node syntax: PASSED;
- Alembic: one head `0016_universe_replay_asof`;
- focused affected suites: PASSED.

Final archive integrity/hash are recorded after packaging outside this source report.

## 10. Not verified

- Real PostgreSQL transaction timing and query plan.
- Real Bybit response latency/partial payload behavior.
- Operator worker service restart and forward run.
- Real candidate gate failures and actual-loss attribution.
- Exact historical orderbook/queue/latency/liquidation mechanics.

## 11. Residual risks

The final inference barrier refreshes tickers, not orderbooks. Execution plans remain correctly fail-closed if orderbook evidence is stale. A large partial all-tickers response can still publish for valid refreshed symbols while skipping absent ones; coverage is now observable. Technical availability does not establish strategy profitability.

## 12. Recommended next work package

Add a bounded decision-snapshot latency budget and exact orderbook coverage telemetry around plan construction, then validate it with production JobRun timings before considering any concurrency refactor.
