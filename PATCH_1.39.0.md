# Patch 1.39.0 — decision-time execution snapshot barrier

Date: 2026-07-07

## Problem

Release 1.35.5 refreshed tickers immediately before inference, but execution-plan construction in the same transaction also requires a fresh order book and, for `bybit_read_only` profiles, a fresh account-equity snapshot. Those inputs were not refreshed at the same boundary.

The startup sequence made the defect deterministic:

1. `market_job(backfill=True)` fetched order books first;
2. initial last/mark/index candle and funding/OI backfill could then run for a long time;
3. startup catch-up inference refreshed only tickers;
4. the first `account_job()` ran only after catch-up inference.

Consequently, newly published signals could still have substantial signal TTL remaining while every associated execution plan was `BLOCKED_STALE_DATA` because account state was missing or order books had aged beyond policy. This matches the observed cards marked “Устаревшие данные” with approximately 1h23m remaining. The eight-hour model horizon was not the stale-data timer: default signal TTL is 90 minutes, orderbook freshness is 90 seconds and account freshness is 180 seconds.

## Correction

- Added one shared `_refresh_execution_inputs()` boundary used by hourly and universe-catchup inference.
- For read-only account mode it refreshes wallet/equity and positions first.
- It then refreshes active-universe order books and finally the all-tickers batch immediately before publication.
- A private-account refresh exception aborts the inference transaction before signal publication.
- A non-empty universe with zero stored or idempotently-covered order books aborts fail-closed.
- Partial orderbook success remains visible in `JobRun.details.execution_input_refresh`; publication continues and existing per-symbol freshness/depth checks block only affected symbols.
- Successful inference updates the worker account-sync watermark, avoiding an unnecessary immediate duplicate startup account job.

## Training-history finding

The observed `4 из 1206` counter is not caused by slow candle backfill. In dynamic mode the trainer deliberately applies prospective point-in-time universe replay. Rows before the first committed universe-eligibility snapshot are excluded because historical membership and executable spread decisions cannot be reconstructed from candles alone. Therefore, after four hours of ledger operation, the honest replay cohort contains approximately four unique decision hours even if 365 days of candles are present.

The required 1206 timestamps derive from warm-up, 8-hour labels, purged train/calibration/holdout geometry, minimum 168-hour final holdout and expanding walk-forward folds. This patch does not lower that requirement or fabricate pre-ledger eligibility.

## Compatibility

- Database migration: none; Alembic head remains `0017_model_artifact_blobs`.
- New `.env` variables: none.
- Active artifacts, features, labels and promotion policy are unchanged.
- Freshness thresholds and signal TTL are unchanged.
- Advisory-only and read-only Bybit boundaries are preserved.

## Validation

Baseline 1.38.0:

- full suite: `750 passed, 8 skipped`;
- Ruff, compileall and JavaScript syntax passed;
- `pip check` reported the pre-existing global-environment `moviepy`/Pillow conflict.

Red evidence against untouched 1.38.0:

- `tests/unit/test_decision_execution_snapshot_freshness_2026_07_07.py`: `5 failed` because account/orderbook refresh and zero-coverage fail-closed behavior were absent.

Release 1.39.0:

- new regression suite: `5 passed`;
- combined ticker/execution freshness suite: `10 passed`;
- full suite: `755 passed, 8 skipped`;
- Ruff, compileall and JavaScript syntax passed;
- one Alembic head: `0017_model_artifact_blobs`.

PostgreSQL integration and live Bybit execution were not run because no isolated database/account environment was supplied.

## Operator action

1. Stop the inference worker.
2. Replace application files; no migration or `.env` edit is required.
3. Restart the worker.
4. Existing blocked plans are immutable historical calculations; wait for the next hourly/catch-up publication or explicitly trigger the supported recalculation workflow.
5. Inspect `execution_input_refresh` in the corresponding `JobRun.details` if plans remain blocked.

This patch fixes false mass staleness caused by publication ordering. It does not prove profitability, increase model quality or bypass genuine stale/private-API failures.
