# Patch 1.8.20 — acceptance external-state integrity

## Problem

An `ACTIONABLE` execution plan could reach `ACCEPTED` after its external assumptions had become unverifiable:

1. missing `funding_rate` or `next_funding_time` was converted to a zero projected funding cost;
2. read-only account reconciliation was performed when a plan was built, but not repeated at acceptance;
3. the turnover-derived liquidity cap was not recomputed at acceptance;
4. missing turnover during plan construction removed the liquidity cap instead of blocking the plan.

Because the product is advisory-only, these defects did not place an exchange order automatically. They could still present an unsafe plan as accepted and understate costs, portfolio exposure or market-impact risk.

## Resolution

- Added one Decimal-safe `liquidity_notional_cap()` policy function using `turnover_24h × 0.0001`.
- Plan creation requires positive finite turnover; invalid input produces `BLOCKED_DATA` diagnostics.
- Acceptance requires complete current funding metadata, repeats account reconciliation for read-only profiles and compares current plan notional with the fresh liquidity cap.
- Changed external inputs return HTTP 409 `PLAN_RECALCULATION_REQUIRED`; the old mutable plan becomes `SUPERSEDED` and a new plan version is built under current data.
- Stored the current liquidity cap in the operator decision context.

## Compatibility

- Database migration: none.
- `.env` changes: none.
- Public API schema: unchanged.
- Advisory-only and PostgreSQL-only boundaries: unchanged.
- Rollback: stop API/worker/trainer, restore 1.8.19 source, restart. No database downgrade is needed.

## Verification

Baseline in an isolated Python 3.13.5 environment: 323 passed, 4 skipped. Four focused regressions failed on unchanged 1.8.19 for the expected reasons. Post-change target: 333 passed, 4 skipped; Ruff, compileall, pip check and JavaScript syntax must pass. PostgreSQL integration and live Bybit smoke remain environment-dependent and are not claimed here.
