# QA Report

Release: **1.39.0**

Date: **2026-07-07**
Scope: **decision-time account/orderbook/ticker freshness before signal and execution-plan publication**

## Environment

- Python: 3.13.5.
- Project requirement: Python >=3.12.
- Input archive: `cost_aware_momentum-1.38.0-trainer-preflight-scope.zip`.
- Input SHA-256: `7f6efb51c22252b39e8c4f869e1e1d53492df2643be6bd4d5400a1d3eaf5a526`.
- Source version: 1.38.0.
- Alembic head before and after: `0017_model_artifact_blobs`.
- Baseline inventory: 102 production/script/web files, 103 test files, 15 documentation files and 17 migration revisions.
- Separate PostgreSQL integration database: not configured.

## Baseline before production changes

| Check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | FAILED: unrelated global-environment conflict — `moviepy 2.2.1` requires `pillow<12`, installed Pillow is 12.2.0 |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 750 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |

`python manage.py doctor` and `python manage.py test --require-integration` were not run because no operator configuration or isolated PostgreSQL test URL was available. The operator database was not accessed.

## Confirmed defects

### 1. Startup catch-up published before the first account snapshot — HIGH

The initial worker sequence called `catchup_inference_job()` before `account_job()`. For a `bybit_read_only` capital profile, execution-plan construction therefore saw no verified equity snapshot and set every plan to `BLOCKED_STALE_DATA`, even though the market signal itself was fresh.

Expected: account-dependent plan construction uses a current account snapshot.

Actual: the first account sync happened only after startup plans had been persisted.

### 2. Slow startup/backfill aged order books before publication — HIGH

`market_job(backfill=True)` fetched order books before initial candle/mark/index and funding/OI work. Startup catch-up later refreshed tickers only. After a long bootstrap, order books could be hours old while signals still had a new 90-minute TTL.

Expected: every mutable execution input is refreshed immediately before plan construction.

Actual: the decision-time barrier covered ticker only.

### 3. Complete account/orderbook refresh failure still allowed a mass blocked publication — MEDIUM

A private-account exception or zero successful orderbook refreshes should stop the publication transaction rather than write a whole universe of plans known in advance to be blocked.

## Finding about `4 из 1206`

This counter is deliberate in dynamic mode. The trainer requires prospective point-in-time universe replay and excludes all candle rows before the first committed universe-eligibility snapshot. Historical candle backfill does not reconstruct historical membership and executable spread decisions. Therefore four hours of eligibility-ledger operation produce approximately four honest unique decision timestamps even when older candles are present.

The 1206 requirement is derived from feature warm-up, the 8-hour outcome horizon, purged temporal splits, minimum 168-hour holdout and expanding walk-forward folds. It was not reduced.

## Red evidence

The final regression file was run against an untouched 1.38.0 tree:

```text
python -m pytest -q tests/unit/test_decision_execution_snapshot_freshness_2026_07_07.py
```

Result: **5 failed** for the intended reasons:

- hourly and catch-up inference refreshed only tickers;
- zero orderbook coverage did not abort;
- private account failure did not abort;
- manual-capital path had no orderbook refresh boundary.

## Implemented correction

- Added one shared `_refresh_execution_inputs()` boundary.
- Read-only account state is refreshed first when configured.
- Active-universe order books are refreshed next.
- Tickers are refreshed last, immediately before publication.
- Zero orderbook coverage and private-account failure abort before signal write.
- Partial orderbook coverage is retained in job diagnostics and remains subject to per-symbol fail-closed checks.
- Hourly and catch-up inference use exactly the same boundary.
- Successful account refresh updates the worker watermark, preventing an immediate redundant startup account job.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | FAILED: same unrelated `moviepy`/Pillow global-environment conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| new regression suite | PASSED: 5 passed |
| combined decision freshness suite | PASSED: 10 passed |
| `python -m pytest -q` | PASSED: 755 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED: one head, `0017_model_artifact_blobs` |

No previously passing test regressed. The eight skipped tests are PostgreSQL integration contracts requiring an isolated database.

## Migration, configuration and compatibility

- New migration: none.
- New `.env` variable: none.
- Active model artifacts and training contracts are unchanged.
- `SIGNAL_TTL_MINUTES=90`, `MAX_ORDERBOOK_AGE_SECONDS=90`, `MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS=180` and `MAX_TICKER_AGE_SECONDS=120` remain unchanged.
- Advisory-only and read-only Bybit boundaries remain intact.
- Existing blocked plans are immutable historical calculations; new plans are produced by the next supported publication/recalculation cycle.

## Not run / residual limitations

- No live PostgreSQL worker startup was executed.
- No real Bybit public/private API refresh was executed.
- Bounded sequential orderbook refresh duration for the operator's full universe was not benchmarked.
- Partial orderbook failures can still leave individual plans blocked, correctly and visibly.
- Dynamic history before the prospective universe ledger remains intentionally unavailable.
- This correction does not prove economic edge or causally explain all prior losses.
