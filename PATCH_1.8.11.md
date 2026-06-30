# Patch 1.8.11 — horizon-aware policy and quantitative integrity

## Problem

The 1.8.10 audit baseline was green, but focused independent tests reproduced quantitative fail-open paths that existing tests did not cover:

- holdout policy drawdown/total R treated every overlapping hourly H-horizon decision as a fully funded independent bet;
- model promotion accepted policy metrics without an explicit horizon/accounting schema;
- TP/TIMEOUT returns and label-end timestamps could contradict their barrier contract;
- a recalculated execution plan reused the signal-time cumulative funding scenario;
- fractional leverage was silently truncated;
- hourly outcome evaluation accepted non-hourly or internally inconsistent OHLC bars;
- manual entry/close fills could be recorded in the future.

## Solution

- policy metrics now use `exit-time-horizon-sleeves-v2`, divide each hourly cohort contribution by `H`, and bind schema/horizon/sleeve count to the model artifact;
- metadata validation requires exact TP barrier returns, TIMEOUT inside both barriers and exact `decision_time + horizon` label end;
- execution-plan funding is reprojected from `planning_time`; unknown interval metadata blocks a known non-zero settlement;
- leverage uses strict positive-integer validation in sizing and liquidation checks;
- outcome evaluation enforces the configured interval and `low <= close <= high`; intrabar calls pass their own interval and use `primary-barrier-intrabar-v3`;
- manual fill timestamps must be timezone-aware and not later than server time.

## Database migration

None. Alembic head remains `0006_manual_trade_remaining_risk`.

## Configuration

No new environment variables. Existing leverage values must be positive integers.

## Model compatibility

Recompute candidate/incumbent policy metrics. Legacy payloads without:

- `policy_metric_schema=exit-time-horizon-sleeves-v2`;
- `policy_horizon_hours` equal to artifact horizon;
- `policy_capital_sleeves` equal to artifact horizon

are rejected by the promotion gate rather than compared under incompatible semantics.

## Verification

- input baseline: `252 passed, 4 skipped`;
- independent red evidence: 12 focused cases failed on unmodified 1.8.10;
- corrected focused cases: 12 passed;
- complete post-change suite: `264 passed, 4 skipped, 19 warnings`;
- pip check, compileall, Ruff, frontend syntax and release integrity: `PASSED`.

PostgreSQL integration, migration upgrade/downgrade and runtime doctor were not run because no isolated PostgreSQL/runtime configuration was available.

## Limitations

This patch does not establish profitability. Counterfactual PlanOutcome still estimates crossed funding settlements from the immutable plan snapshot rather than joining every historical realized funding row. Multi-fold walk-forward/OOF aggregation, repeated-final-holdout governance, historical order-book execution and live drift/forward evidence remain separate work packages.
