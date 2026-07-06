# Patch 1.35.0 — mature counterfactual outcome attribution

Date: 2026-07-06

## Problem

`candidate-live-attrition-report-v2` counted where signal and execution-plan opportunities
were filtered, but it never loaded the already persisted `SignalOutcome` and `PlanOutcome`
rows. The report therefore could not distinguish:

- an actionable cohort that later reached SL;
- a `NO_TRADE` cohort that later reached TP;
- a risk/liquidity blocker followed by TIMEOUT;
- a correctly avoided loss from a potentially over-restrictive filter.

The missing join made the report unsuitable for evidence-based investigation of rare signals
and repeated losses. It did not prove that any gate was wrong, so no threshold was relaxed.

## Implemented change

- Upgraded the report schema to `candidate-live-attrition-report-v3`.
- Extracted exact `signal_id` and `plan_id` values from prospective inference evidence.
- Loaded only matching `MarketSignal`, `SignalOutcome` and `PlanOutcome` rows in bounded
  batches.
- Added `live.outcome_attribution` with:
  - full-horizon maturity coverage;
  - TP/SL/TIMEOUT and ambiguous-outcome counts;
  - plan valuation-status coverage;
  - descriptive `counterfactual_r` sign split, mean, median and sum for `VALUED` plans;
  - groupings by initial plan status, terminal stage and primary reason.
- Excluded early TP/SL outcomes until the complete configured horizon has elapsed.
- Enforced point-in-time availability: an outcome is visible only when its timezone-aware `resolved_at` is not after `report.until`; later-resolved rows are counted as excluded evidence.
- Failed closed on missing mature signal/plan outcomes, duplicate/conflicting evidence,
  signal/plan outcome mismatch and invalid valuation/R combinations.
- Marked the report explicitly with `actual_execution_pnl=false` and `causal_claim=false`.

## Compatibility

- Database migration: none.
- New environment variables: none.
- Model artifact/feature/label/class schema: unchanged.
- HTTP/frontend contract: unchanged.
- Risk, policy, quality and activation thresholds: unchanged.
- Bybit access remains read-only and advisory-only.

`build_attrition_report_from_records` keeps its old pure-call behavior when outcome inputs are
not requested. The production database path always supplies all three outcome datasets and
therefore applies the new fail-closed checks.

## Validation

Baseline 1.34.2:

- `694 passed, 7 skipped, 62 warnings`;
- Ruff, compileall, pip check, JavaScript syntax and the single Alembic head passed.

Release 1.35.0:

- `699 passed, 7 skipped, 62 warnings`;
- 8 attrition tests passed;
- Ruff, compileall, pip check, JavaScript syntax and Alembic head
  `0016_universe_replay_asof` passed;
- advisory-only boundary scan passed.

PostgreSQL integration tests were skipped because no isolated `TEST_DATABASE_URL` was
available.

## Operator action

1. Replace the application with release 1.35.0.
2. Restart API/worker processes that build reports.
3. Allow the counterfactual outcome job to resolve full-horizon cohorts.
4. Run:

```bash
python manage.py attrition-report -- --hours 168
```

A `BLOCKED` outcome-attribution section must be investigated rather than bypassed. Plans with
`NOT_SIZED`, `FUNDING_UNAVAILABLE`, `PATH_UNAVAILABLE` or `INVALID_INPUT` intentionally have
no fabricated counterfactual R.
