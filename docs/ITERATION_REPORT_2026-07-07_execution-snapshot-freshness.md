# Iteration report — decision-time execution snapshot freshness

Date: 2026-07-07  
Target release: 1.39.0

## 1. Input archive

- Archive: `cost_aware_momentum-1.38.0-trainer-preflight-scope.zip`
- SHA-256: `7f6efb51c22252b39e8c4f869e1e1d53492df2643be6bd4d5400a1d3eaf5a526`
- Source version: 1.38.0
- Python requirement: >=3.12
- Alembic head: `0017_model_artifact_blobs`
- Baseline inventory: 102 production/script/web files, 103 test files, 15 documentation files, 17 migrations.

No production `.env`, credentials, database dumps, real artifacts or release build directories were present in the input archive.

## 2. Goal and acceptance criteria

After this iteration, every actual hourly and universe-catchup publication must refresh all mutable inputs required for execution-plan construction immediately before signal publication, without widening freshness windows or model/risk gates.

Acceptance criteria:

1. Read-only account state is refreshed before plan construction when enabled.
2. Active-universe order books are refreshed after account state and before the final ticker batch.
3. Hourly and catch-up inference use one shared ordering contract.
4. Private account refresh failure aborts before any signal write.
5. A non-empty universe with zero successful/idempotently-covered order books aborts before publication.
6. Manual capital mode does not require private account API access.
7. Existing ticker freshness behavior and all prior tests remain green.
8. No freshness threshold, signal TTL, quality gate, EV/RR threshold or risk limit is relaxed.

## 3. Sources read and data flow

Read:

- `README.md`, `CHANGELOG.md`, `PATCH_1.35.4.md`, `PATCH_1.35.5.md`, `PATCH_1.36.0.md`, `PATCH_1.37.0.md`, `PATCH_1.38.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- `app/workers/runner.py`, `app/services/market_data.py`, `app/services/signals.py`, `app/services/execution.py`, `app/services/market_snapshots.py`, `app/api/serializers.py`, `app/config.py`;
- decision freshness, orderbook, account snapshot and trainer readiness tests.

Affected live flow before the patch:

`market_job orderbooks -> potentially long initial backfill -> ticker refresh -> catchup inference -> signal/plan construction -> first account sync`

Corrected flow:

`read-only account refresh -> active-universe orderbook refresh -> final ticker refresh -> signal and execution-plan publication`

## 4. Baseline

Commands executed from the source root before production changes:

```text
python --version
python -m pip check
python -m compileall -q app scripts tests manage.py
python -m ruff check .
python -m pytest -q
node --check web/js/app.js
```

Results:

- Python 3.13.5 — PASSED.
- `pip check` — FAILED because the shared environment has `moviepy 2.2.1` requiring `pillow<12`, while Pillow 12.2.0 is installed. The project does not declare moviepy.
- compileall — PASSED.
- Ruff — PASSED.
- pytest — PASSED: 750 passed, 8 skipped.
- JavaScript syntax — PASSED.

`manage.py doctor` and PostgreSQL integration were not run because no isolated test database/operator configuration was provided.

## 5. Confirmed defects and finding

### Defect A — startup catch-up before account snapshot

Severity: HIGH  
Classification: CONFIRMED DEFECT

`Worker.run()` invoked `catchup_inference_job("startup_backfill")` before the first `account_job()`. `build_execution_plan()` requires a fresh read-only account snapshot and therefore persisted `BLOCKED_STALE_DATA` plans for every read-only profile at first publication.

Expected: fresh account state exists before account-dependent plan calculation.

Actual: first account sync occurred only after startup plan persistence.

Why tests missed it: prior decision-freshness tests covered only ticker ordering.

### Defect B — order books aged during slow startup/backfill

Severity: HIGH  
Classification: CONFIRMED DEFECT

`market_job(backfill=True)` fetched order books first and then could spend a long time on candle/mark/index and funding/OI bootstrap. Catch-up and hourly inference refreshed tickers only. A new signal with a 90-minute TTL could therefore be paired with an orderbook snapshot older than the 90-second policy limit.

This explains the observed UI combination “Устаревшие данные” while approximately 1h23m remained. The card status was execution-data freshness, not expiry of the 8-hour prediction horizon.

### Defect C — known all-symbol refresh failure still published blocked plans

Severity: MEDIUM  
Classification: CONFIRMED DEFECT

A complete private-account failure or zero orderbook refresh coverage did not stop signal publication. The transaction could write a whole universe of plans known in advance to be blocked.

### Finding — `4 из 1206`

Classification: DOCUMENTED LIMITATION / INTENDED FAIL-CLOSED BEHAVIOR

Dynamic trainer readiness applies prospective point-in-time universe replay. All decision rows before the first committed universe-eligibility snapshot are deliberately excluded. Historical candles cannot reconstruct the historical selected-symbol membership or executable spread decision.

Therefore four hours of eligibility-ledger operation produce approximately four honest unique timestamps even when 365 days of candles have been downloaded. The 1206 threshold is derived from feature warm-up, the 8-hour label horizon, purged train/calibration/holdout geometry, minimum 168-hour holdout and expanding walk-forward folds. It was not reduced.

## 6. Plan and actual diff

Production:

- `app/workers/runner.py`
- `app/__init__.py`
- `pyproject.toml`

Tests:

- new `tests/unit/test_decision_execution_snapshot_freshness_2026_07_07.py`
- updated `tests/unit/test_decision_ticker_refresh_2026_07_07.py`

Documentation/release:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.39.0.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- this report
- `SHA256SUMS`

No migration or `.env` change was required.

## 7. Red -> green evidence

Final regression file copied into an untouched 1.38.0 tree:

```text
python -m pytest -q tests/unit/test_decision_execution_snapshot_freshness_2026_07_07.py
```

Red result: `5 failed`.

The failures independently showed:

- missing account refresh in hourly inference;
- missing account/orderbook refresh in catch-up inference;
- no zero-orderbook-coverage abort;
- no account-refresh-failure abort;
- no orderbook refresh in manual-capital mode.

After implementation, the same command returned `5 passed`.

Combined old/new decision freshness suite returned `10 passed`.

## 8. Compatibility

- Database migration: none.
- Alembic head remains `0017_model_artifact_blobs`.
- New environment variables: none.
- API schema: existing job details gain `execution_input_refresh`; existing `decision_ticker_refresh` is retained.
- Artifact/feature/label/promotion contracts: unchanged.
- Advisory-only and read-only Bybit boundary: unchanged.
- Existing immutable blocked plans are not rewritten retrospectively.

## 9. Post-check

```text
python -m pip check
python -m compileall -q app scripts tests manage.py
python -m ruff check .
python -m pytest -q
node --check web/js/app.js
python -m alembic heads
```

Results:

- `pip check` — FAILED with the same external moviepy/Pillow conflict as baseline.
- compileall — PASSED.
- Ruff — PASSED.
- pytest — PASSED: 755 passed, 8 skipped.
- JavaScript syntax — PASSED.
- Alembic — PASSED: one head, `0017_model_artifact_blobs`.

No previously green test regressed.

## 10. Not verified

- Live startup against the operator PostgreSQL database.
- Real Bybit public/private account requests.
- Full-universe orderbook refresh duration and rate-limit behavior.
- PostgreSQL integration suite.
- The exact count of the operator's plans blocked by account versus orderbook freshness.
- Economic profitability and causal attribution of prior manual losses.

## 11. Residual risks and limitations

- Partial orderbook failures can correctly block individual symbols.
- A very large/slow universe may still cause early orderbook rows to approach the 90-second freshness limit; live job details must be reviewed.
- Dynamic pre-ledger history remains unavailable by design.
- Fixing false staleness does not make baseline signals actionable when `ALLOW_BASELINE_ACTIONABLE=false` and does not improve model edge.

## 12. Rollback

1. Stop the inference worker.
2. Restore the 1.38.0 application tree.
3. Restart the worker.
4. No database downgrade or `.env` rollback is needed.

Rollback reintroduces the startup account/orderbook ordering defect but does not alter persisted schema or model artifacts.

## 13. Recommended next work package

Add bounded stage-by-stage trainer readiness attribution that separately reports:

`confirmed last candles -> continuity -> mark/index/OI/funding context -> prospective universe/spread replay -> labels -> temporal split -> holdout -> walk-forward`.

The report must distinguish raw historical depth from prospective dynamic eligibility, without fabricating pre-ledger membership or lowering 1206.
