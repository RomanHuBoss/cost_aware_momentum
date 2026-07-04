# Iteration Report — hourly decision-candle retry

## 1. Input archive, hash and versions

- Input: `cost_aware_momentum-main.zip`.
- SHA-256: `4e78746d3336f3611dab0dd4cf47ee70104fac868ed35f67b319c69de3f12a1e`.
- Source version: `1.9.3`.
- Result version: `1.9.4`.
- Python requirement: `>=3.12`; test runtime: Python 3.13.5.
- Input release integrity: 177 files checked / 177 manifest entries; no `.env`, credentials, virtualenv, caches, dumps or real model artifacts.
- Alembic: 9 revisions, one head `0009_candle_receipt_availability`; no migration in this patch.

## 2. Iteration goal and acceptance criteria

After this iteration, a partial hourly candle fetch must remain fail-closed but trigger a bounded real refetch of missing exact decision candles, confirmed by independent coverage and retry regressions.

Acceptance criteria:

1. Coverage is evaluated per symbol against a confirmed `last` candle with `close_time == event_time`.
2. Per-symbol fetch exceptions and empty/partial payloads remain isolated and visible in diagnostics.
3. A partial `hourly_market_close` success is retryable after cooldown and performs the network fetch again.
4. Complete coverage and zero universe are not retried.
5. Retry count is persisted under a job-specific key and stops after five retries.
6. Existing inference retry behavior remains compatible.
7. No decision-candle, ML-quality, EV/RR, risk, advisory-only or PostgreSQL boundary is weakened.
8. No migration, dependency, public API or `.env` change is introduced.

## 3. Sources read and affected data flow

Read before modification:

- `README.md`, `CHANGELOG.md`, `PATCH_1.9.2.md`, `PATCH_1.9.3.md`;
- `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- recent iteration reports and the source DOCX specification sections relevant to hourly ingestion, fail-closed inference and process separation;
- market-data ingestion, worker job idempotency/retry, exact signal publication, Bybit read-only client, ML lifecycle, risk/cost/execution services and related tests.

Affected flow:

`Bybit public kline GET → per-symbol normalization/upsert → exact last-candle coverage diagnostics → PostgreSQL JobRun → bounded hourly-market refetch → inference reads PostgreSQL → exact decision-candle gate → signal`.

Inference does not perform network I/O. Market signal economics, capital-dependent execution plans and model lifecycle are unchanged.

## 4. Baseline before production edits

The system Python was not a valid project environment: `ruff` and `psycopg` were absent and global `pip check` reported an unrelated MoviePy/Pillow conflict. The native setup workflow created an isolated `.venv`; baseline was repeated there before code edits.

| Command | Result |
|---|---|
| `.venv/bin/python --version` | PASSED — Python 3.13.5 |
| `.venv/bin/python -m pip check` | PASSED — no broken requirements |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED |
| `.venv/bin/python -m ruff check .` | PASSED |
| `.venv/bin/python -m pytest -q` | PASSED — **444 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED |
| `.venv/bin/python -m alembic heads` | PASSED — one head `0009_candle_receipt_availability` |
| input release integrity | PASSED — 177/177 |
| `.venv/bin/python manage.py doctor` | FAILED / ENVIRONMENT — default development secrets, missing PostgreSQL CLI/server |
| `.venv/bin/python manage.py test --require-integration` | NOT RUN — no isolated PostgreSQL URL/server; user/production DB not used |

Warnings are unchanged third-party NumPy/joblib deprecations in serialization tests.

## 5. Confirmed defect and evidence

### HIGH — partial candle fetch became terminal success without refetch

Production paths:

- `app/services/market_data.py::sync_candles` catches each symbol/price-type exception, logs it and returns the rows that did succeed.
- `app/workers/runner.py::hourly_market_close_job` returned only aggregate row count.
- `app/workers/runner.py::run_job` stored any non-raising result as `SUCCESS` and skipped the same `(job_name, scheduled_for)` thereafter.
- `app/workers/runner.py::inference_job` retried incomplete publication, but only queried PostgreSQL.
- Minute `market_job` refreshes tickers; candles are fetched there only for newly admitted symbols.

Minimal reproduction:

1. BTC exact hourly candle fetch succeeds; ETH raises a transient timeout.
2. `sync_candles` inserts BTC and returns normally.
3. `hourly_market_close` is persisted as `SUCCESS` without per-symbol coverage.
4. ETH inference returns `missing_decision_candle`.
5. Subsequent hourly-market calls are skipped; inference retries never refetch ETH.

Expected: partial exact-candle coverage remains fail-closed and schedules bounded refetch.

Actual before fix: partial fetch became terminal for the current hour.

Impact: a transient public API failure could suppress recommendations for affected symbols until the next hour. This can materially reduce the signal funnel. It does not create a false actionable signal and does not prove the cause of any historical losing trade.

Why existing tests missed it: exact decision-candle publication and incomplete inference retry were tested separately; no test connected per-symbol fetch failure to market-job idempotency/refetch semantics.

External claims of fixed counts of critical/medium errors were not accompanied by modules, stack traces, datasets or reproductions and were not treated as evidence.

## 6. Plan and actual diff

Production:

- `app/services/market_data.py` — optional exact-close diagnostics, request counters and per-symbol coverage.
- `app/workers/runner.py` — generic incomplete-coverage predicate; job-specific retry keys; bounded `hourly_market_close` refetch.

Tests:

- new `tests/unit/test_hourly_candle_retry_2026_07_04.py` — partial timeout coverage, retry configuration, completion and retry-limit behavior.
- existing `tests/unit/test_inference_retry.py` remains green and verifies backward-compatible inference semantics.

Release/docs:

- version sources, README, architecture, operator/incident documentation;
- changelog, `PATCH_1.9.4.md`, QA, compliance, traceability, this report and manifest.

No migration, ORM, API schema, frontend, dependency or environment file changed.

## 7. Red → green evidence

Command before production fix:

```bash
.venv/bin/python -m pytest -q tests/unit/test_hourly_candle_retry_2026_07_04.py
```

RED:

```text
TypeError: sync_candles() got an unexpected keyword argument 'required_close_time'
KeyError: 'retry_incomplete_success'
2 failed in 2.87s
```

The failures prove both missing contracts: no exact coverage diagnostics and no retry configuration on the hourly market-close job.

After production fix, including existing inference retry tests:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_hourly_candle_retry_2026_07_04.py \
  tests/unit/test_inference_retry.py
```

GREEN:

```text
7 passed in 3.40s
```

## 8. Migration, API/config/env compatibility

- Migration: none; Alembic head unchanged.
- Database schema/ORM: unchanged.
- Public HTTP API and frontend contract: unchanged.
- Bybit methods: existing public/read-only GET only; no order mutation.
- New dependencies: none.
- New `.env` variables: none.
- Model artifacts, feature/label schemas, trainer and activation gates: unchanged.
- `sync_candles` keeps its integer return contract; new keyword arguments are optional.

## 9. Post-check

| Command | Result |
|---|---|
| `.venv/bin/python -m pip check` | PASSED — no broken requirements |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED |
| `.venv/bin/python -m ruff check .` | PASSED |
| `.venv/bin/python -m pytest -q` | PASSED — **448 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED |
| `.venv/bin/python -m alembic heads` | PASSED — one head `0009_candle_receipt_availability` |
| `.venv/bin/python manage.py doctor` | FAILED / ENVIRONMENT — unchanged local PostgreSQL/secrets limitations |
| PostgreSQL integration suite | NOT RUN — isolated server/URL unavailable |
| final manifest, archive and clean re-extraction | PASSED — 180/180 manifest entries; `unzip -t` and clean re-extraction passed |

No previously green test regressed.

## 10. Not verified

- Real PostgreSQL transaction/advisory-lock execution; schema did not change and no isolated server was available.
- Live Bybit timeout/rate-limit behavior; tests use deterministic fakes and no order endpoint.
- User database, JobRun history, actual signal funnel, model candidates, fills or outcomes.
- Causal explanation of historical losses or forward profitability.

## 11. Residual risks and limitations

- Five refetch attempts cannot repair a sustained exchange/network outage; diagnostics now make that state explicit.
- A symbol can still correctly remain `NO_TRADE` after the exact candle arrives because model, spread, slippage, funding, EV/RR, risk or capital gates reject it.
- A model trained for one day may correctly fail temporal-depth and quality gates; this patch intentionally does not reduce them.
- Actual historical order-book/fill/funding parity remains partial in research.
- Full walk-forward, drift/regime governance, PBO/DSR and forward profitability evidence remain incomplete.

## 12. Rollback procedure

1. Stop API, worker and trainer.
2. Restore the complete 1.9.3 source archive; no database downgrade is required.
3. Regenerate/recheck `SHA256SUMS` for the restored tree.
4. Restart processes and verify one Alembic head.
5. Be aware that rollback reopens the confirmed no-refetch path for partial hourly candle loads.

## 13. Recommended next work package

Add an append-only hourly decision funnel that records the first blocking reason per symbol across exact candle availability, feature validity, model provenance, scenario geometry, spread/slippage/funding, net EV/RR and capital/risk policy. Pair it with candidate-gate rejection decomposition. This is the next evidence-driven step for diagnosing remaining sparse recommendations and models that do not pass gates without weakening safety thresholds.
