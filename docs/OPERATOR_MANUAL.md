# Operator manual

## Recommendation workflow

1. Open the local UI and authenticate.
2. Select or review the active capital profile.
3. Review signal direction, entry zone, TP/SL, model diagnostics, and execution plan.
4. Treat all statuses beginning with `BLOCKED_` as non-executable until the underlying reason is resolved.
5. Accept/reject advisory plans only after reviewing reason codes, risk, margin, liquidity, and freshness diagnostics.
6. Record manual entries/exits only for operator-managed trades.

## Important statuses

- `ACTIONABLE`: plan currently passes configured checks.
- `LIMITED`: plan is executable but constrained by a cap.
- `BLOCKED_MIN_SIZE`: safe size is below exchange minimum order size.
- `BLOCKED_LIQUIDITY`: safe size cannot be filled within liquidity policy.
- `BLOCKED_MARGIN`: free margin after reserve is insufficient.
- `BLOCKED_PORTFOLIO`: portfolio risk cap is exhausted.
- `BLOCKED_EXCHANGE`: current exchange/instrument cap prevents a safe executable size.
- `BLOCKED_STALE_DATA` / `BLOCKED_DATA`: required evidence is stale, missing, or invalid.

## 1.52.13 note

A plan blocked by exchange notional/maxQty caps is now shown separately from minimum-order failures. Do not resolve `BLOCKED_EXCHANGE` by increasing risk or rounding quantity upward.

## 1.52.18 candle-data note

Malformed Bybit candle rows are no longer persisted. If current-hour candle coverage is missing after an exchange/API anomaly, treat the recommendation path as stale/missing data and retry after data recovery rather than overriding the gate.
