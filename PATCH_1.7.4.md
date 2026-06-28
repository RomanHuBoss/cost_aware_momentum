# Patch 1.7.4 — fail-closed directional geometry

## Problem

The risk layer converted stop and take-profit distances with `abs()`. An inverted LONG/SHORT geometry therefore looked like a valid positive distance:

- LONG could accept `stop >= entry` or `take_profit <= entry`;
- SHORT could accept `stop <= entry` or `take_profit >= entry`.

A corrupted, imported or legacy signal could consequently receive non-zero sizing. The post-event outcome evaluator already rejected such geometry, so execution planning and outcome accounting did not share one contract.

## Change

- Added one reusable `validate_directional_geometry()` contract in `app/risk/math.py`.
- Replaced absolute directional distances with signed LONG/SHORT formulas.
- `net_rr_and_ev()` now rejects inverted, non-positive and non-finite entry/SL/TP values.
- `calculate_position_plan()` accepts the primary take-profit and returns `BLOCKED_INVALID_INPUT`, zero quantity/notional and `INVALID_GEOMETRY` when validation fails.
- Execution-plan construction passes TP1 into sizing, preserves blocking status before `NO_TRADE`, and skips liquidation calculations for invalid inputs.
- Manual fills beyond the directional stop boundary return HTTP 422 instead of an unhandled exception.
- Counterfactual outcome evaluation uses the same validator.

## Compatibility

- Patch release; public REST response schemas and database schema are unchanged.
- Existing valid signals and plans retain the same calculations.
- No Alembic migration is required; head remains `0004_counterfactual_outcomes`.
- No new `.env` variables are required.
- Invalid legacy/imported signals are intentionally blocked and must be corrected at their source.

## Verification

- RED: `python -m pytest -q tests/unit/test_risk_math.py` → 5 failed for four inverted geometries and missing TP-aware sizing contract.
- GREEN targeted: risk and outcome modules pass.
- Full suite, Ruff, compileall, JavaScript syntax and Alembic head are recorded in `docs/QA_REPORT.md` and `docs/ITERATION_REPORT_2026-06-28-directional-geometry.md`.
