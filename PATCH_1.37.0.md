# Patch 1.37.0 — executable-spread replay alignment

Date: 2026-07-07

## Problem

Dynamic universe discovery and live execution used different spread contracts by design:

- `UNIVERSE_MAX_SPREAD_BPS=30` admitted instruments for observation;
- `MAX_SPREAD_BPS=18` blocked live signal publication when the current bid/ask spread was wider.

The immutable universe snapshot already stored each selected instrument's point-in-time bid, ask and `spread_bps`, but research replay retained only `selected_symbols`. Training, candidate policy evaluation and formal backtests therefore included selected observations with spread between 18 and 30 bps even though the live layer would always skip the same cohort. The live executable threshold was also absent from the immutable promotion-policy binding, and candidate `training_data_profile` described the source candle frame rather than the exact post-replay model cohort.

This mismatch could inflate or otherwise distort policy trade-rate and OOS evidence, make candidate/live attrition appear unexplained, and allow evidence produced under one live spread threshold to be reused after the threshold changed. It did not prove that a looser threshold would be profitable, so the live limit was not increased.

## Correction

- Universe as-of loader validates full immutable snapshots and derives `execution_eligible_symbols` from each selected decision's stored `ticker.spread_bps` using the exact configured `MAX_SPREAD_BPS`.
- Replay schema v2 filters model rows by that executable cohort and reports exact threshold, spread-excluded row count and affected selected symbols.
- Replay rejects a threshold mismatch instead of silently reusing evidence produced under another executable-spread contract.
- Background preflight, actual fit, manual training and formal backtest all pass the same configured threshold.
- Promotion-policy binding schema v3 includes `maximum_executable_spread_bps`; normal activation therefore requires exact spread-policy equality.
- Candidate training-data profile is computed from the actual post-replay barrier dataset, deduplicated from LONG/SHORT rows to one source candle per symbol/hour.

## Compatibility

- Database migration: none. Alembic head remains `0017_model_artifact_blobs`.
- New `.env` variables: none.
- Existing immutable universe snapshots remain usable because per-symbol spread evidence was already persisted in `decisions`.
- Existing active artifact may continue inference.
- An inactive candidate or experiment evidence with policy-binding schema v2 cannot satisfy the new ordinary promotion contract; retrain/re-run governed evidence under the current `MAX_SPREAD_BPS`.
- Universe replay evidence schema changes from v1 to v2.
- No quality, walk-forward, holdout, minimum trade-rate, spread, EV/RR, leverage or risk limit is relaxed.

## Validation

Baseline 1.36.0:

- full suite: `738 passed, 8 skipped`;
- Ruff, compileall and JavaScript syntax passed;
- `pip check` reported an unrelated global-environment conflict: `moviepy 2.2.1` requires `pillow<12`, while Pillow 12.2.0 is installed.

Red evidence against untouched 1.36.0:

- `tests/unit/test_executable_spread_replay_alignment_2026_07_07.py`: `6 failed` because spread-aware replay APIs/profile helper did not exist and policy binding remained v2.

Release 1.37.0:

- focused regression suite: `6 passed`;
- full suite: `744 passed, 8 skipped`;
- Ruff, compileall and JavaScript syntax passed;
- one Alembic head: `0017_model_artifact_blobs`.

PostgreSQL integration was not executed because no isolated test database was configured.

## Operator action

1. Stop trainer and any research/backtest processes.
2. Replace application files; no migration is required beyond the existing 1.36.0 head.
3. Keep `MAX_SPREAD_BPS` at the intended live executable threshold; do not raise it merely to increase signal count.
4. Restart trainer.
5. Allow old inactive v2-bound candidates to be terminally rejected/closed, then create a fresh candidate and governed backtest evidence.
6. Inspect replay evidence for `spread_ineligible_rows_excluded` and `spread_ineligible_selected_symbols` before interpreting low trade rate.

This patch makes research evidence more conservative and comparable to live behavior. It does not claim profitability and may reduce the nominal historical sample because previously untradeable observations are no longer counted.
