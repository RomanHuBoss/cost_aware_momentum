# Configuration

Configuration is read from environment variables documented in `.env.example` and validated by `app.config.Settings`.

## Required production principles

- `DATABASE_URL` must use PostgreSQL through `postgresql+psycopg://`.
- Production must not rely on demo seed data or the uncalibrated baseline model for actionable recommendations.
- Bybit credentials, when supplied, are used only for read-only account endpoints.
- Risk, fee, slippage, funding, spread, leverage, and margin parameters must remain conservative and explicit.

## 1.52.13 changes

No new variables were introduced. Existing exchange/instrument limits are now surfaced more accurately by the sizing engine:

- exchange notional cap breaches return `BLOCKED_EXCHANGE`;
- exchange-limited plans retain `LIMITED` but include an operator warning;
- UI and attrition diagnostics preserve the exchange-cap cause.

## 1.52.18 changes

No new configuration variables were introduced. Existing candle ingestion now fails closed on malformed OHLCV rows before persistence.

## 1.52.19 changes

No new `.env` variables are required. Existing mark/index synchronization can stay enabled; the ingestion path now accepts the documented price-only Bybit mark/index kline shape while preserving strict ordinary last-trade OHLCV validation.
## 1.52.20 changes

No new `.env` variables are required. Existing orderbook settings remain unchanged, but depth snapshots now fail closed if the normalized top of book is locked or crossed (`best_ask <= best_bid`).

## 1.52.21 changes

No new `.env` variables are required. Existing mark/index synchronization remains enabled as before, but malformed partial mark/index kline rows now fail closed when only one of the optional volume/turnover fields is present. Five-field price-only mark/index rows remain supported.

## 1.52.24 authentication changes

No environment variable was renamed or added, but production validation is stricter:

- `APP_MODE=production` requires `COOKIE_SECURE=true`; otherwise settings construction fails.
- Browser access uses the signed `cam_session` cookie and `X-CSRF-Token` for mutating requests.
- Machine clients and authenticated readiness probes should set a strong `OPERATOR_API_TOKEN` and send it as `X-Operator-Token`.
- `COOKIE_SECURE=false` remains valid only outside production for local HTTP development/paper operation.

After deployment, update the readiness probe to call `/health/ready` with `X-Operator-Token`; `/health/live` remains anonymous and may be used as the minimal liveness probe.
