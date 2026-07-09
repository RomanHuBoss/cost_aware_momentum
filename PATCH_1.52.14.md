# PATCH 1.52.14 — validated-cash-inputs

Date: 2026-07-09

## Summary

This patch hardens low-level monetary helper functions used by realized and estimated accounting. It prevents impossible cash-flow states from being silently produced when invalid signed notionals or negative fee rates reach shared risk math helpers.

## Confirmed defects fixed

### A. Negative funding notional inverted trader-perspective funding sign

- Type: CONFIRMED DEFECT
- Severity: medium
- File: `app/risk/math.py`
- Function: `funding_cash_flow()`
- Actual behavior: `funding_cash_flow("LONG", Decimal("-1000"), Decimal("0.0001"))` returned a positive cash flow, turning a LONG funding debit into a credit.
- Expected behavior: funding cash-flow requires a positive finite position value; invalid notional must fail closed.
- Fix: normalize `position_value` through `positive_finite_decimal(..., "position_value")` before applying the directional funding sign.
- Regression: `tests/unit/test_risk_math.py::test_funding_cash_flow_rejects_negative_position_value`.

### B. Negative fee rate produced impossible negative fee cash

- Type: CONFIRMED DEFECT
- Severity: medium
- File: `app/risk/math.py`
- Function: `fee_cash()`
- Actual behavior: a negative `fee_rate` produced negative fee cash, effectively a hidden rebate.
- Expected behavior: execution fee cash requires finite quantity, positive finite execution price, and non-negative finite fee rate.
- Fix: validate quantity, execution price, and fee rate before arithmetic.
- Regression: `tests/unit/test_risk_math.py::test_fee_cash_rejects_negative_fee_rate`.

## Compatibility

- Version type: patch.
- Database migration: not required.
- `.env` changes: none.
- API schema changes: none.
- Bybit endpoint changes: none.
- Advisory-only invariant: preserved; no order create/amend/cancel/withdraw capability added.

## Verification

```bash
python -m pytest -q \
  tests/unit/test_risk_math.py::test_funding_cash_flow_rejects_negative_position_value \
  tests/unit/test_risk_math.py::test_fee_cash_rejects_negative_fee_rate
# .. [100%]
# 2 passed in 0.11s

python -m pytest -q tests/unit/test_risk_math.py
# ................................ [100%]
# 32 passed in 0.16s
```

Full pytest remains blocked in this sandbox by missing `psycopg`; ruff remains unavailable because the module is not installed. See `docs/QA_REPORT.md` and `docs/ITERATION_REPORT_2026-07-09_validated-cash-inputs.md`.
