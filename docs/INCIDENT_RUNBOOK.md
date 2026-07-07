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

## Model/trainer failed or deferred

Не деактивируйте incumbent. Сохраните job/audit evidence, artifact SHA, data profile и gate reasons. Повторное обучение допускается только по scheduler/recovery contract или явному operator action.

Если job имеет PostgreSQL status `SUCCESS`, но `details.status=DEFERRED`, это ожидаемая fail-closed остановка до регистрации candidate, а не повреждение trainer. Для `insufficient_walk_forward_history_after_filtering` сравните `walk_forward_capacity.actual_timestamps` и `required_timestamps`, затем проверьте gaps, context/spec/funding/mark coverage и symbol attrition. Не уменьшайте folds, purge или holdout. Scheduler повторит попытку только после новых timestamps или material data-profile change.

## Stale/invalid market or account state

Не принимайте plan. Проверьте timestamps, confirmed candle, ticker/orderbook/spec/funding snapshots, account capital и reconciliation.

## Suspected loss or bad recommendation

Зафиксируйте signal/plan/model versions, decision/availability times, bid/ask/orderbook, actual fills/fees/funding и outcome. Не объявляйте причиной модель до воспроизводимого point-in-time replay.
