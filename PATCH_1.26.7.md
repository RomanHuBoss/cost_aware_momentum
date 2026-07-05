# Patch 1.26.7 — cost-stress experiment promotion gate

## Problem

The backtest already calculated terminal `stress_net_return_cost_x1_5` and `stress_net_return_cost_x2`, but those values were informational only. The append-only successful experiment event persisted the nominal hourly return path, and experiment governance selected/promoted a trial without requiring either stressed path. A family could therefore become `READY` even when the selected policy compounded to a loss after the specification-mandated cost multipliers.

## Solution

- Build cumulative hourly mark-to-market capital paths for ×1.5 and ×2 using the same observed-period grid and selected trades as nominal evidence.
- Preserve the prior stress semantics: scale fees/slippage, adverse funding and residual stop-gap reserve; do not rerun direction/actionability selection under hindsight.
- Persist schema `hourly-mark-to-market-cost-stress-v1` in every successful experiment event.
- Validate exact timestamp alignment, finite period returns, scenario multipliers, terminal compounding and maximum drawdown.
- Add a fail-closed non-negative terminal-return requirement for both scenarios. A statistically admissible selected trial that fails it returns `REJECTED_COST_STRESS`.
- Raise the preregistered governance report to v4 and persisted promotion gate to v3 so legacy gate v2 cannot bypass the new invariant.

## Compatibility

- Database migration: none.
- Public API and `.env`: unchanged.
- Model feature/label/runtime artifact schemas: unchanged.
- Recommendation thresholds and advisory-only/read-only boundaries: unchanged.
- Active models are not deactivated. Existing successful experiment events without cost-stress v1 and inactive candidates with promotion gate v2 require governed backtest reruns/re-evaluation.

## Verification

- Baseline: `622 passed, 4 skipped, 62 warnings`.
- Red evidence: two targeted tests failed because cost-stress paths were absent and missing stress evidence was accepted.
- Green evidence: both targeted tests pass.
- Post-change suite: `627 passed, 4 skipped, 62 warnings`.
- `pip check`, `compileall`, `ruff`, frontend `node --check`, version consistency and single Alembic head pass in the isolated environment.
- PostgreSQL integration was not run because no isolated test database URL is configured.

## Remaining limitations

The fixed multipliers are deterministic sensitivity scenarios, not an orderbook/latency simulator. They do not prove profitability, sufficient recommendation frequency or resilience to nonlinear impact, partial fills, dynamic fee tiers, queue position, cross margin or regime change. Gates were not weakened.
