# Patch 1.9.5 — policy actionability-density gate

## Problem

The trainer already emitted `policy_candidates`, `policy_trades` and `policy_trade_rate`, but the automatic promotion gate ignored the rate. A candidate could therefore pass the absolute trade and cohort minima with only a microscopic selected fraction, for example 80 policy trades among 100,000 evaluated symbol/timestamp candidates.

That behavior is economically and statistically unsafe: a few selected outcomes can look profitable while the model remains operationally almost silent and highly sensitive to sampling error. It is a confirmed gate defect, but it does not prove that every sparse recommendation or user loss had this cause.

## Resolution

- Added `AUTO_TRAIN_MIN_POLICY_TRADE_RATE=0.01` with validation in `(0, 1]`.
- Promotion now requires `policy_trade_rate >= threshold` in addition to absolute trade and independent-cohort minima.
- The gate validates `policy_candidates`, `policy_trades`, and `policy_trade_rate` for finiteness, range and arithmetic consistency.
- Missing or contradictory evidence fails closed with explicit reasons.
- Status diagnostics expose the effective threshold and quality-gate output records candidate count, observed rate and minimum rate.

## Compatibility

- Patch release: `1.9.5`.
- No Alembic migration; head remains `0009_candle_receipt_availability`.
- No dependency or order-execution change; advisory-only and PostgreSQL-only boundaries are unchanged.
- Existing `.env` files remain valid because the new variable has a default. Operators may add it explicitly for auditability.
- Current v10 policy metrics already contain the required evidence; no artifact schema bump is needed.

## Verification

- Red: `test_quality_gate_rejects_statistically_sparse_policy` showed the sparse candidate incorrectly passed.
- Green: sparse policy is rejected; a policy exactly at 1% passes; inconsistent ratios and invalid thresholds fail closed.
- Full static/unit checks are recorded in `docs/QA_REPORT.md` and the iteration report.

## Limitation

This patch does not lower live EV/RR/risk gates and does not create more recommendations. It prevents automatic activation of a model whose actionability is too sparse to support the operational conclusions implied by promotion. Profitability still requires OOS and forward/shadow evidence.
