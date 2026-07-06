# Patch 1.28.0 — risk-budgeted experiment portfolio accounting

## Problem

Formal experiment/backtest evidence used equal-notional allocation inside fixed horizon capital sleeves. Production execution plans use a different contract: notional is derived from per-trade stress-risk budget, existing open stress risk remains reserved until exit, and new plans are constrained by aggregate open-risk and margin capacity.

This mismatch could change portfolio weights, drawdown and model-selection statistics. A deterministic two-trade example demonstrates a sign reversal: equal notional reports `-1.5%`, while equal 0.35% stress-risk budgets report `+0.525%`.

## Solution

- Added deterministic risk-budgeted portfolio replay for formal experiment evidence.
- Simultaneous candidates receive equal desired stress-risk budgets and are proportionally scaled without inventing operator order.
- Existing positions reserve absolute stress risk and notional until modeled exit.
- New entries are limited by remaining aggregate open-risk capacity and leverage-adjusted margin after reserve.
- Nominal, stop-reserve, ×1.5 and ×2 cost-stress paths use the same sizing semantics.
- Added allocation diagnostics to backtest results.
- Added `risk_rate`, `max_total_open_risk_rate` and `margin_reserve_rate` to experiment policy binding.
- Raised experiment return, cost-stress and policy-binding schemas to v4/v2/v2.

## Compatibility

- Database migration: none.
- Public HTTP API: unchanged.
- `.env`: no new variables; existing `DEFAULT_RISK_RATE`, `MAX_TOTAL_OPEN_RISK_RATE` and `MARGIN_RESERVE_RATE` are now bound to experiment evidence.
- Model feature/label/runtime artifact schemas: unchanged.
- Active artifacts remain runnable.
- Inactive candidates with policy-binding v1 and experiment families with equal-notional v3 paths must be retrained/rerun before normal promotion.

## Verification

Baseline:

```text
636 passed, 4 skipped, 62 warnings
```

Red:

```text
python -m pytest -q tests/unit/test_risk_budgeted_experiment_accounting_2026_07_06.py
ImportError: cannot import name '_simulate_risk_budgeted_portfolio_evidence'
```

Green targeted:

```text
8 passed
```

Full post-change suite:

```text
641 passed, 4 skipped, 62 warnings
```

## Limitations

The research replay does not reconstruct historical min-order constraints, exact depth/partial fills, instrument notional caps, profile-specific account state or manual operator ordering. It is a deterministic sizing approximation, not evidence of profitability or an exchange-accurate OMS simulation.
