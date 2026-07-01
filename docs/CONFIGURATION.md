# Configuration

Основной шаблон: `.env.example`. Значения читаются `app.config.Settings`.

Критические группы:

- Runtime: `APP_MODE`, `APP_HOST`, `APP_PORT`, `SECRET_KEY`, `OPERATOR_PASSWORD`.
- PostgreSQL: `DATABASE_URL`; для integration tests — отдельный `TEST_DATABASE_URL` или безопасный admin URL для создания временной БД.
- Bybit: `BYBIT_BASE_URL`, optional read-only credentials и `BYBIT_READ_ONLY_ACCOUNT`.
- Universe/ingestion: `UNIVERSE_*`, `INITIAL_BACKFILL_BARS`, `HISTORY_BACKFILL_*`, `MARKET_POLL_SECONDS`, `INSTRUMENT_REFRESH_SECONDS`.
- Risk/economics: `DEFAULT_RISK_RATE`, `MAX_TOTAL_OPEN_RISK_RATE`, `MIN_NET_RR`, `MIN_NET_EV_R`, fee/slippage/gap reserve и freshness limits.
- Model lifecycle: `AUTO_TRAIN_*`, `MODEL_DIR`, `ACTIVE_MODEL_PATH`.

## Изменения 1.8.28

Новых переменных нет.

- `UNIVERSE_ALLOW_NON_CRYPTO_SYMBOL_TYPES=false` теперь явно исключает известные Bybit TradFi product families `stock`, `forex`, `commodity`, `xstocks` и `xstock` из crypto model domain.
- Значения `symbolType`, обозначающие обычные криптовалютные регионы/сегменты (например, `innovation`), не блокируются.
- `UNIVERSE_ALLOW_NON_CRYPTO_SYMBOL_TYPES=true` сохраняет прежний явный opt-in и допускает эти типы. Используйте его только при отдельной модели, данных и risk policy для соответствующего market domain.
- Bybit credentials, endpoints, PostgreSQL schema и остальные policy defaults не изменены.

## Семантика 1.8.27

- Для `manual`/`paper` `allocated_capital` является также теоретической базой доступной маржи; к ней применяется существующий `margin_reserve_rate`.
- Account/profile-scoped margin уже принятых планов, а для manual/paper также открытых journal trades, вычитается до sizing и acceptance.
- Денежная `fee` ручного входа заменяет модельную entry-leg комиссию при расчёте stress loss.
- Фактический stress loss и margin requirement не могут превышать reservations принятого immutable execution plan.
