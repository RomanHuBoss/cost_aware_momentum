# Patch 1.7.5 — fail-closed numeric sizing inputs

## Problem

`calculate_position_plan()` validated directional entry/SL/TP geometry but trusted the remaining Decimal inputs. Corrupted/imported PostgreSQL rows or malformed external snapshots could therefore cross the financial risk boundary:

- `NaN` capital, available margin, caps or `qty_step` raised an unhandled `decimal.InvalidOperation`/`ValueError`;
- infinite risk rate could produce a non-blocked plan;
- `margin_reserve_rate=1` was accepted and classified through ordinary sizing;
- negative fee/slippage/reserve values reduced downside and could produce an `ACTIONABLE` plan.

PostgreSQL `NUMERIC` can represent non-finite values, so API validation alone is not a sufficient service-layer invariant.

## Change

- Added reusable finite, positive and non-negative Decimal validators in `app/risk/math.py`.
- Position sizing validates capital, risk rate, cost assumptions, instrument constraints, margin reserve and all optional notional caps before arithmetic.
- Invalid values return `BLOCKED_INVALID_INPUT` with zero qty/notional/loss/margin and a field-specific diagnostic.
- Invalid-plan capital and risk outputs are sanitized to finite values so persistence/API serialization cannot receive `NaN` or `Infinity`.
- Signed finite funding remains supported because its sign has directional economic meaning.
- Existing directional-geometry failures retain `INVALID_GEOMETRY`; other numeric failures use `INVALID_INPUT`.

## Compatibility

- Patch release; REST schemas, PostgreSQL schema and valid numerical results are unchanged.
- No Alembic migration is required; head remains `0004_counterfactual_outcomes`.
- No new `.env` variables are required.
- Corrupted legacy/imported rows intentionally change from exception/fail-open behavior to a zero-sized block.

## Verification

- RED: `python -m pytest -q tests/unit/test_risk_math.py` → `7 failed, 19 passed` across capital, risk, margin, reserve, cap, qty-step and negative-fee cases.
- GREEN targeted: `python -m pytest -q tests/unit/test_risk_math.py` → `26 passed`.
- Full suite, Ruff, compileall, JavaScript syntax and Alembic head are recorded in `docs/QA_REPORT.md` and `docs/ITERATION_REPORT_2026-06-28-risk-input-validation.md`.
