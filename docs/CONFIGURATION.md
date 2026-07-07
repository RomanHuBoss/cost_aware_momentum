# Configuration

Канонический перечень переменных и безопасные примеры находятся в `.env.example`; реальные credentials в release не входят.

## Основные группы

- PostgreSQL connection и migration readiness.
- Local bind/auth/CSRF/idempotency.
- Bybit public/read-only account access.
- Universe, candle, ticker, orderbook и staleness limits.
- Fee, slippage, stop-gap, funding, RR/EV и portfolio risk limits.
- Trainer scheduling, holdout, calibration, policy и promotion gates.
- Drift monitoring, backups и operational retention.

## Версия 1.52.0

Добавлены:

- `AUTO_TRAIN_DYNAMIC_BOOTSTRAP_ENABLED=true` — разрешает hash-bound historical bootstrap на текущем dynamic cohort.
- `AUTO_TRAIN_BOOTSTRAP_MIN_SYMBOLS=3` — минимальный execution-eligible cohort.
- `AUTO_TRAIN_BOOTSTRAP_INSTRUMENT_SPEC_EXTRA_TICKS=1` — консервативный adverse tick stress для часов до первой локальной instrument-spec записи.

`AUTO_TRAIN_MAX_SYMBOLS` применяется к frozen bootstrap cohort. Exact prospective dynamic replay не ограничивается full-sample coverage ranking, чтобы исключить selection look-ahead.

## Release check

Из чистого корня:

```bash
python manage.py release-check --write
python manage.py release-check
```

Первая команда пересчитывает `SHA256SUMS`; обе команды fail-closed проверяют состав, версии, forbidden artifacts и checksums.
