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

Оставить incumbent active, заблокировать candidate activation, проверить hash/task/classes/horizon/calibration, `feature_schema_version`, `label_path_schema_version`, `temporal_split_schema` и ATR barrier multipliers. Не сравнивать candidate с incumbent при различной barrier geometry; переобучить совместимый artifact или выполнить documented rollback.


## PATH_UNAVAILABLE или подозрительный plan outcome

1. Не трактовать нулевые financial fields как безубыточную сделку: проверить `valuation_status`.
2. Сравнить `plan.sizing_snapshot.planning_time` с `signal.event_time`.
3. Не переиспользовать signal-level TP/SL path для более позднего entry.
4. Для восстановления денежной оценки требуется доказуемый entry-aligned intrabar path; без него оставить запись fail-closed.
5. После migration 0008 проверить число переведённых historical rows и сохранить результат в операционном журнале.
