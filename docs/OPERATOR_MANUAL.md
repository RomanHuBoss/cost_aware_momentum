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

## 1.52.19 mark/index candle-data note

If previous logs showed `candle_validation_failed` with `missing kline.volume` during mark/index synchronization, upgrade to 1.52.19 and rerun candle sync/backfill. Ordinary last-trade candles still require exchange volume/turnover; do not override missing-volume failures for `price_type=last`.


## 1.52.21 mark/index candle-data note

If mark/index backfill or synchronization reports a `volume and turnover must be both present or both absent` validation error, treat it as malformed exchange payload evidence. Do not override the gate; retry or backfill after data recovery.

## 1.52.22 UI safety note

Recommendation detail fields such as profile names, model/version strings, statuses, and audit values are displayed as text in generic data lists. The UI preserves Take Profit line breaks without allowing raw HTML in those fields.

## 1.52.23 locked ticker note

When a Bybit ticker reports `bid == ask`, the system treats the executable quote as invalid. The symbol may retain a last price for observation, but it is excluded from dynamic eligibility and cannot produce or validate an actionable plan until a strictly positive spread (`ask > bid`) is observed. Do not override this gate as a zero-cost market condition.

## 1.52.24 authenticated operator surface

After upgrade, anonymous requests to capital profiles, recommendations, trades, portfolio risk, detailed readiness/status, and `/api/v1/events` receive `401`. Log in through the UI or use `X-Operator-Token` for machine clients. Browser logout requires the current CSRF token and may return `403` when a stale tab or client omits it; re-authenticate rather than bypassing the check. Production deployments must use HTTPS with `COOKIE_SECURE=true`. Configure automated `/health/ready` probes with `X-Operator-Token`; keep `/health/live` for anonymous liveness only.

## 1.52.25 delayed-data retry note

When the first hourly inference pass reports a temporary data-availability reason such as `missing_decision_candle` or `incomplete_market_context`, the worker now retries that exact decision on the existing cooldown, up to five times and only inside the configured publication window. A spread, entry-zone, model, drift, economics, or expired-window rejection is not retried. Use the latest `hourly_inference` diagnostics to distinguish “data still arriving” from a deliberate `NO TRADE`/blocked decision.
