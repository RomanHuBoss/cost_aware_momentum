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


## Signal economics skips across many symbols

If logs show `Skipping symbol with invalid signal economics`, read `reason_code` before changing thresholds:

- `quote_outside_decision_entry_zone`: executable bid/ask moved outside the immutable decision-time entry band; investigate publication lag, ticker freshness and spread.
- `executable_quote_not_tick_aligned`: bid/ask reference is not aligned to current instrument tick size; check ticker/spec snapshots and point-in-time spec selection.
- `no_tick_inside_decision_entry_zone`: entry band is too narrow to contain an exchange tick for the current decision anchor/ATR/tick-size combination; preserve fail-closed behavior and inspect artifact/runtime contract.
- `directional_prediction_contract_invalid` or `signal_policy_funding_contract_invalid`: treat as model/runtime policy contract evidence and do not publish the signal.

Do not widen entry-zone, extend publication delay, round quotes upward/downward or force recommendations merely to reduce skipped symbols. Capture the JSON fields `contract_error`, `reason_detail`, bid/ask, decision anchor, entry band and tick size, then replay the decision point-in-time.

## Stale/invalid market or account state

Не принимайте plan. Проверьте timestamps, confirmed candle, ticker/orderbook/spec/funding snapshots, account capital и reconciliation.

Если acceptance возвращает `Current executable price is outside entry zone`, не обходите это ручным accept/retry: текущий FULL-fill VWAP вышел за immutable decision-time support старого signal. Создайте/дождитесь нового plan по свежему signal или проверьте lag между публикацией и решением оператора.

## Suspected loss or bad recommendation

Зафиксируйте signal/plan/model versions, decision/availability times, bid/ask/orderbook, actual fills/fees/funding и outcome. Не объявляйте причиной модель до воспроизводимого point-in-time replay.
