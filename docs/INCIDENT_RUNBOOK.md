# Incident Runbook

## Общий принцип

При неоднозначности сохраняйте действующий безопасный state и блокируйте новые рекомендации/acceptance до установления причины. Не ослабляйте gates ради восстановления потока сигналов.

## Release integrity failed

1. Не запускайте полученный архив.
2. Сохраните вывод `python manage.py release-check`.
3. Проверьте missing/unlisted/modified/forbidden files и три version markers.
4. Удалите caches, secrets и runtime artifacts.
5. Исправьте документы/версию, пересоздайте `SHA256SUMS`, повторите verification.

## Migration/readiness failed

Не используйте `create_all` или SQLite fallback. Проверьте URL отдельной PostgreSQL, Alembic head и backup/restore evidence.

## Model/trainer failed

Не деактивируйте incumbent. Сохраните job/audit evidence, artifact SHA, data profile и gate reasons. Повторное обучение допускается только по scheduler/recovery contract или явному operator action.

## Stale/invalid market or account state

Не принимайте plan. Проверьте timestamps, confirmed candle, ticker/orderbook/spec/funding snapshots, account capital и reconciliation.

## Suspected loss or bad recommendation

Зафиксируйте signal/plan/model versions, decision/availability times, bid/ask/orderbook, actual fills/fees/funding и outcome. Не объявляйте причиной модель до воспроизводимого point-in-time replay.
