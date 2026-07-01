# Incident Runbook

## Stale или missing market data

1. Не обходить fail-closed gate.
2. Проверить worker heartbeat, Bybit connectivity и последние job diagnostics.
3. Проверить `received_at`/`available_at`, candle continuity и instrument spec freshness.
4. После восстановления повторно запустить ingestion; не редактировать confirmed candles вручную.

## Подозрение на revision confirmed candle

1. Остановить публикацию затронутого symbol/time range.
2. Сохранить внешний payload и текущую строку для расследования.
3. Не выполнять прямой UPDATE подтверждённого OHLCV.
4. До реализации revision quarantine оставить первый confirmed snapshot неизменным и зафиксировать incident.

## Database/migration mismatch

Не запускать штатные процессы до совпадения Alembic head. Использовать backup/restore procedure и отдельную тестовую БД для проверки migration.

## Model incident

Оставить incumbent active, заблокировать candidate activation, проверить hash/task/schema/classes/horizon metadata и выполнить documented rollback.
