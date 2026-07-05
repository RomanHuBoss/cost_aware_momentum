# Patch 1.22.0 — point-in-time funding interval replay

Date: 2026-07-05

## Problem

`load_training_market_data()` loaded all `InstrumentSpecHistory` rows but collapsed them to one latest `funding_interval_minutes` value per symbol. The same latest value was then applied to every historical settlement and every historical `funding_age_fraction` observation.

For a symbol whose interval changed, for example from 8 hours to 4 hours, a complete older 8-hour settlement sequence was checked against a 4-hour grid. This could falsely report a missing settlement, discard otherwise valid label cohorts and prevent a candidate from reaching the normal quality gates. The context feature was also scaled by the wrong interval for older rows. Existing tests covered only a constant interval and therefore did not expose the defect.

## Solution

- Added `FundingIntervalSchedule` with point-in-time lookup by `InstrumentSpecHistory.valid_from`.
- Passed full positive interval history through background training, manual training and research backtest.
- Historical replay validates exact cadence on stable segments and applies conservative transition validation when an observed interval change occurs.
- Market context computes funding age with the interval effective at each decision timestamp.
- Candidate metadata records schedule schema, source, observed changes and symbols requiring a backward assumption before the first local spec row.
- Promotion and runtime validation require point-in-time interval evidence.
- Advanced semantic contracts:
  - feature: `hourly-barrier-market-context-v5`;
  - context: `hourly-oi-basis-settled-funding-turnover-v2`;
  - historical funding: `bybit-settlement-timestamp-replay-v2`;
  - interval schedule: `instrument-spec-point-in-time-v1`;
  - policy metrics: `decision-open-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v16`.

## Compatibility

- Database migration: none. Alembic head remains `0014_ui_exposure_ledger`.
- `.env` changes: none.
- Model artifacts: incompatible by design. Artifacts from 1.21.0 and earlier must be retrained after instrument/funding history synchronization.
- Advisory-only, PostgreSQL-only and process separation remain unchanged.
- Rollback: restore the 1.21.0 source and its prior active artifact. No schema downgrade is required.

## Verification

Baseline before changes:

- dependency check, compileall, Ruff and JavaScript syntax: passed;
- pytest: `582 passed, 4 skipped, 61 warnings`;
- Alembic head: `0014_ui_exposure_ledger`.

Red evidence:

- `tests/unit/test_point_in_time_funding_intervals_2026_07_05.py` initially failed with three `TypeError` errors because interval history was not accepted by replay or context construction.

Post-change:

- focused interval tests: passed;
- full pytest and release checks: recorded in `docs/QA_REPORT.md` and the iteration report.

## Limitations

`InstrumentSpecHistory` is a prospective local observation ledger. For training timestamps before its earliest row, the earliest observed interval is used and disclosed as a backward assumption. This patch does not reconstruct unavailable pre-observation schedules or historical funding forecasts. Passing technical gates does not establish profitability or guarantee more recommendations.
