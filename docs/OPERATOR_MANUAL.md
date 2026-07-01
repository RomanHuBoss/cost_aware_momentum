# Operator Manual

## Запуск

Используйте `manage.py setup`, `configure`, `db-init`, `migrate`, `doctor`, затем `run`. Web UI по умолчанию доступен только на `127.0.0.1:8000`.

## Интерпретация

- Market signal не зависит от капитала профиля.
- Execution plan зависит от капитала, account snapshot, маржи, ликвидности и exchange constraints.
- `BLOCKED`/`NO TRADE` нельзя трактовать как LONG или SHORT.
- Перед ACCEPTED система повторно валидирует freshness, risk, margin, funding, instrument specs и plan version.

## После обновления на 1.8.25

Migration и новые env-переменные не нужны. Перезапустите worker/API/trainer штатной командой. При следующем ingestion confirmed candle rows больше не будут молча перезаписываться; это не требует backfill или ручной правки БД.
