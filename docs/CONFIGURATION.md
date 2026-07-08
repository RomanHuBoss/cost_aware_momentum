# Configuration

## Startup training backfill

- `INITIAL_BACKFILL_BARS=1500` — default startup candle depth. It intentionally exceeds the current default training readiness minimum of 1206 label-eligible hourly timestamps.
- Bybit kline responses are single-page bounded; the worker paginates startup candle requests when this value is greater than 1000.
- Existing `.env` files with `INITIAL_BACKFILL_BARS=1000` remain valid but may leave the trainer waiting for progressive history backfill before the first candidate attempt.

## Progressive market-context backfill

- `HISTORY_BACKFILL_PAGES_PER_SYMBOL=2` remains the generic progressive page count for candle/mark/index/funding cycles.
- `HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL=7` is intentionally separate because Bybit hourly open-interest pages are capped at 200 rows. The previous generic 2-page default loaded only about 400 OI hours, which can shrink to about 326 usable development timestamps after point-in-time market-context and label filtering while current walk-forward requires 366.
- Do not reduce open-interest pages to make training start sooner; insufficient OI history correctly defers training fail-closed.

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
