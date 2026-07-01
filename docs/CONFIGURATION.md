# Configuration

Основной шаблон: `.env.example`. Значения читаются `app.config.Settings`.

Критические группы:

- Runtime: `APP_MODE`, `APP_HOST`, `APP_PORT`, `SECRET_KEY`, `OPERATOR_PASSWORD`.
- PostgreSQL: `DATABASE_URL`; для integration tests — отдельный `TEST_DATABASE_URL` или безопасный admin URL для создания временной БД.
- Bybit: `BYBIT_BASE_URL`, optional read-only credentials и `BYBIT_READ_ONLY_ACCOUNT`.
- Universe/ingestion: `UNIVERSE_*`, `INITIAL_BACKFILL_BARS`, `HISTORY_BACKFILL_*`, `MARKET_POLL_SECONDS`, `INSTRUMENT_REFRESH_SECONDS`.
- Risk/economics: `DEFAULT_RISK_RATE`, `MAX_TOTAL_OPEN_RISK_RATE`, `MIN_NET_RR`, `MIN_NET_EV_R`, fee/slippage/gap reserve и freshness limits.
- Model lifecycle: `AUTO_TRAIN_*`, `MODEL_DIR`, `ACTIVE_MODEL_PATH`.

## Изменения 1.8.27

Новых переменных нет. Изменена только fail-closed семантика существующих параметров профиля и ручного fill:

- для `manual`/`paper` `allocated_capital` является также теоретической базой доступной маржи; к ней применяется существующий `margin_reserve_rate`;
- account/profile-scoped margin уже принятых планов, а для manual/paper также открытых journal trades, вычитается до sizing и acceptance;
- денежная `fee` ручного входа заменяет модельную entry-leg комиссию при расчёте stress loss;
- фактический stress loss и margin requirement не могут превышать `actual_stress_loss` и `margin_estimate` принятого immutable execution plan;
- изменение не затрагивает Bybit credentials, endpoints, migrations или `.env.example`.
