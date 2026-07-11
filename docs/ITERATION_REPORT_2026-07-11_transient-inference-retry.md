# Iteration report — transient-inference-retry

Date: 2026-07-11  
Release: 1.52.25  
Version type: patch

## 1. Input archive, hash, root, and baseline inventory

- Input ZIP: `cost_aware_momentum-main.zip`
- Input SHA-256: `f5aa3ea2db73642a1f6b55a3161144f3acc38101cb2ba01094b7d4818bf65b95`
- Detected root: `cost_aware_momentum-main/`
- Source version: 1.52.24
- Python requirement: `>=3.12`
- Alembic migrations: 18 files, `0001_initial` through `0018_inference_observations`
- Alembic head: one head, `0018_inference_observations`
- Baseline inventory: 98 production files under `app/` and `scripts/`, 129 test files, 22 files under `docs/`, 299 total files including `SHA256SUMS`
- Unexpected release artifacts before checks: none. No `.env`, credentials, virtual environment, cache, bytecode, dump, database, or real model artifact was present in the input tree.

The attached 13-page PDF was rendered and read as the controlling iteration protocol. No deployment logs, PostgreSQL dump, `.env`, screenshots of authenticated status, or `JobRun` exports were attached, so the deployed two-day incident could not be replayed byte-for-byte.

## 2. Goal and acceptance criteria

Goal: after this iteration, a first hourly inference pass that fails only because required market evidence is temporarily unavailable must be re-evaluated within the same immutable decision window, while genuine policy/market/model/safety rejects remain final.

Acceptance criteria:

1. `missing_decision_candle` and other explicit data-availability outcomes are retryable even when terminal outcome coverage is complete.
2. Retry uses the existing cooldown and stops at the existing five-retry maximum.
3. The existing stale-publication boundary still blocks late publication.
4. Spread, entry-zone, model, drift, and economics outcomes are not retried.
5. A regression fails on 1.52.24 for the correct reason and passes after the minimal fix.
6. Full non-integration tests, Ruff, compile, dependency, JavaScript syntax, Alembic-head, version, release-integrity, and ZIP checks pass.
7. Advisory-only, PostgreSQL-only, signal/plan separation, risk thresholds, artifact lifecycle, API schema, and `.env` contracts remain unchanged.

## 3. Read sources and data-flow map

Read before selecting the fix:

- `README.md`, `CHANGELOG.md`, `PATCH_1.52.21.md` through `PATCH_1.52.24.md`, `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- worker, market-data, signals, execution, runtime selection, trainer/lifecycle, recommendation API, status API, ORM/migrations, and relevant unit tests.

Project map:

1. Bybit read-only client ingests instruments, ticker, candles, mark/index candles, funding, OI, orderbook, and optional read-only account snapshots.
2. `Worker` schedules market sync, historical backfill, exact hourly market close, outcomes, drift, inference, expiry, and retention as PostgreSQL-backed idempotent jobs.
3. Feature/context services build confirmed-candle and point-in-time market-context inputs.
4. Active runtime produces LONG and SHORT TP/SL/TIMEOUT probabilities; the signal policy selects one direction using capital-independent economics.
5. Signal publication persists immutable geometry, audit/outbox evidence, and a terminal symbol outcome.
6. Execution planning applies profile capital, portfolio/account state, orderbook/VWAP, margin, instrument constraints, funding, costs, and risk caps.
7. Authenticated recommendation API/UI displays the latest signal plus profile-specific plan; operator actions remain advisory-only.
8. Trainer, validation, artifact registry, activation, research/backtest, migrations, audit/idempotency, and PostgreSQL state remain separate processes/contracts.

## 4. Baseline commands and exact results

No source file was changed before baseline.

### Host runtime

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.12.13` |
| `python -m pip check` | PASSED | `No broken requirements found.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | host runtime had no `ruff` module |
| `python -m pytest -q` | UNAVAILABLE | host runtime had no `pytest` module |
| `node --check web/js/app.js` | PASSED | exit 0 |

### Isolated project environment

Dependencies were installed from `.[dev]` into a temporary Python 3.12 environment. The first raw suite inherited the host's SOCKS proxy and failed during `httpx.AsyncClient` construction because optional `socksio` was absent: `24 failed, 890 passed, 8 skipped`. This was recorded rather than hidden. With proxy variables removed for the hermetic unit suite, the source baseline was:

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | PASSED | `No broken requirements found.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | `All checks passed!` |
| `python -m pytest -q` | PASSED | `914 passed, 8 skipped in 10.63s` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | SKIPPED | no deployment `.env` or safe PostgreSQL database was supplied |
| `python manage.py test --require-integration` | SKIPPED | no safe `TEST_DATABASE_URL` was supplied |

Controlled baseline counts: 914 passed / 0 failed / 8 skipped / 0 xfailed / 0 errors.

## 5. Confirmed defect

### D1 — CONFIRMED DEFECT — high — transient data skip permanently closes the hour

- File/function: `app/workers/runner.py::should_retry_incomplete_inference`
- Data path: exact hourly close/data refresh → `publish_hourly_signals()` → `SKIPPED` symbol outcome → successful `JobRun` → retry predicate → `already_completed`.
- Actual behavior: once every selected symbol had any terminal outcome, `symbol_outcome_count == symbols_total` made the job non-retryable. The code did not distinguish `missing_decision_candle`/incomplete data from a final spread, model, drift, or economics decision.
- Expected behavior: terminal processing coverage remains complete, but an explicitly transient data-availability reason must stay bounded-retryable while the original event time is still inside the immutable publication window.
- Operational/financial impact: a brief Bybit, network, database, or ingestion delay at the first pass can suppress all otherwise valid advisory opportunities for an hour. Recurrent delay can present as a prolonged empty terminal. The defect does not create unsafe trades; it creates false absence and opportunity loss.
- Why tests missed it: existing tests correctly prevented “few recommendations” from being mistaken for incomplete processing, but had no separate contract for recoverable data outcomes.
- Reproduction: call the predicate with complete symbol coverage, one `SKIPPED/missing_decision_candle`, and retry count zero. Version 1.52.24 returns `False`.
- Regression: `test_complete_hourly_inference_retries_transient_market_data_skip`.

The user's deployed incident remains a correlated observation, not proof that D1 was its only cause. Exact attribution requires the deployed latest `hourly_inference` details and worker logs.

## 6. Plan and actual diff

Production:

- `app/workers/runner.py`: explicit transient-data reason allowlist and bounded retry classification.
- `app/__init__.py`, `pyproject.toml`: version 1.52.25.

Tests:

- `tests/unit/test_inference_retry.py`: three regression cases for transient retry, policy finality, and retry exhaustion.

Documentation/release evidence:

- `README.md`, `CHANGELOG.md`, `PATCH_1.52.25.md`;
- `docs/ARCHITECTURE.md`, `CONFIGURATION.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`;
- this report and regenerated `SHA256SUMS`.

No migration, database model, API route/schema, frontend JavaScript, Bybit client/endpoint, signal math, execution/risk math, trainer, model artifact, threshold, or `.env.example` change was made.

## 7. Red → green evidence

Red command after adding the test and before changing production code:

```bash
python -m pytest -q \
  tests/unit/test_inference_retry.py::test_complete_hourly_inference_retries_transient_market_data_skip
```

Material red result:

```text
AssertionError: assert False
1 failed in 1.60s
```

Green command: identical. Material result:

```text
1 passed in 1.28s
```

All retry-contract tests after the fix:

```text
6 passed in 1.23s
```

Related worker/scheduling/candle/ticker subset:

```text
26 passed in 1.40s
```

## 8. Migration, API, configuration, and compatibility

- Alembic: no migration; head remains `0018_inference_observations`.
- PostgreSQL: schema and stored-data semantics unchanged.
- API/JSON/frontend: unchanged.
- `.env`: no action required. Existing cooldown, five-retry maximum, and `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS` are reused.
- Model artifacts, features, labels, training, validation, promotion/activation, drift thresholds, risk/cost math, and plan statuses: unchanged.
- Advisory-only: no order create/amend/cancel/withdraw implementation added.
- Backward compatibility: older `JobRun` details without `symbol_outcomes` keep the prior coverage fallback.
- Deployment action: restart the worker after replacing the release. Full process restart is acceptable.

## 9. Post-check

| Command/check | Status | Result |
|---|---:|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| new regression alone | PASSED | 1 passed |
| retry regression file | PASSED | 6 passed |
| `python -m pytest -q` | PASSED | 917 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head: `0018_inference_observations` |
| version consistency | PASSED | README / package / app = 1.52.25 |
| forbidden exchange mutation scan | PASSED | no order create/amend/cancel/withdraw method found |
| credential/runtime artifact scan | PASSED | no release secret, `.env`, dump, cache, virtualenv, or real model artifact |
| release integrity | PASSED | 300 eligible files checked against 300 manifest entries |
| clean ZIP re-extraction | PASSED | one root directory; archive SHA-256 is reported in the final handoff |

Post counts: 917 passed / 0 failed / 8 skipped / 0 xfailed / 0 errors.

## 10. Not verified

- PostgreSQL integration/concurrency tests, migration upgrade/downgrade, and `manage.py doctor`: no safe database/deployment configuration was supplied.
- The user's deployed PostgreSQL `JobRun` rows, worker logs, timestamps, active model, universe size, proxy, and Bybit response/rate-limit evidence.
- Real Bybit paper/shadow forward behavior, exact data-publication delay distribution, network faults, and rate limits.
- Live strategy edge or profitability. Unit/backtest evidence is not a profitability claim.

## 11. Residual risks and limitations

1. The patch restores bounded re-evaluation; it cannot manufacture missing/invalid evidence. Persistent data failures still correctly end with no recommendation.
2. `UNIVERSE_MAX_SYMBOLS=0` permits an unbounded dynamic live universe, while orderbook refresh is per symbol. Without deployed timing evidence, latency/rate-limit starvation remains a suspected operational risk rather than a confirmed defect in this iteration.
3. Hourly exact context coverage across last/mark/index/OI/funding should receive PostgreSQL-backed integration tests and explicit per-source timing diagnostics.
4. A deployment with no active profile, authentication failure, stale worker, absent active artifact in production, critical drift quarantine, or exhausted publication window can also legitimately show no cards.
5. The inherited SOCKS proxy test failure shows that proxy-enabled deployments must either supply a compatible HTTPX proxy dependency/configuration or run without that proxy; this patch does not change network routing.

## 12. Rollback procedure

1. Stop the worker.
2. Restore `app/workers/runner.py`, `app/__init__.py`, and `pyproject.toml` from 1.52.24 plus matching documentation/manifest.
3. No database downgrade or `.env` rollback is needed.
4. Restart the worker and verify liveness/status.
5. Be aware that rollback restores the defect: transient data skips again become final for the hour.

## 13. Recommended next work package

Add a PostgreSQL-backed “hourly inference input readiness and latency budget” package: persist and display per-source exact coverage (last/mark/index/OI/funding/ticker/orderbook), bound dynamic-universe refresh work ahead of the decision deadline, and prove with delayed-source integration fixtures that the worker publishes or emits one precise terminal cause before the immutable window closes.
