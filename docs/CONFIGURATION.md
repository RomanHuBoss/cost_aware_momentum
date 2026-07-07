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

## Версия 1.51.1

Новых переменных окружения нет. Обновление не требует изменения `.env`.

## Release check

Из чистого корня:

```bash
python manage.py release-check --write
python manage.py release-check
```

Первая команда пересчитывает `SHA256SUMS`; обе команды fail-closed проверяют состав, версии, forbidden artifacts и checksums.
