# Configuration

Основной шаблон: `.env.example`. Значения читаются `app.config.Settings`.

Критические группы:

- Runtime: `APP_MODE`, `APP_HOST`, `APP_PORT`, `SECRET_KEY`, `OPERATOR_PASSWORD`.
- PostgreSQL: `DATABASE_URL`; для integration tests — отдельный `TEST_DATABASE_URL` или безопасный admin URL для создания временной БД.
- Bybit: `BYBIT_BASE_URL`, optional read-only credentials и `BYBIT_READ_ONLY_ACCOUNT`.
- Universe/ingestion: `UNIVERSE_*`, `INITIAL_BACKFILL_BARS`, `HISTORY_BACKFILL_*`, `MARKET_POLL_SECONDS`, `INSTRUMENT_REFRESH_SECONDS`.
- Risk/economics: `DEFAULT_RISK_RATE`, `MAX_TOTAL_OPEN_RISK_RATE`, `MIN_NET_RR`, `MIN_NET_EV_R`, fee/slippage/gap reserve и freshness limits.
- Model lifecycle: `AUTO_TRAIN_*`, `MODEL_DIR`, `ACTIVE_MODEL_PATH`.

## Изменения 1.8.26

Новых переменных нет, но усилена fail-closed валидация:

- `MIN_NET_EV_R` не может быть отрицательным.
- Когда одновременно включены `AUTO_TRAIN_ENABLED=true` и `AUTO_TRAIN_AUTO_ACTIVATE=true`, `AUTO_TRAIN_MIN_POLICY_REALIZED_MEAN_R` должен быть не ниже 0, а `AUTO_TRAIN_MIN_POLICY_PROFIT_FACTOR` — не ниже 1.
- Для контролируемого research/backtest допускаются более мягкие policy thresholds только при `AUTO_TRAIN_AUTO_ACTIVATE=false`; они не могут автоматически продвинуть artifact.

Execution plan без явно переданного entry использует текущий ask для LONG и bid для SHORT. Отсутствующий или некорректный top-of-book блокирует план; historical signal reference сохраняется только как помеченная diagnostic basis и не считается исполнимой ценой.
