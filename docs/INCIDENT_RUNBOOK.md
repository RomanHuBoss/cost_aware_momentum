# Incident Runbook

## Stale или missing market data

1. Не обходить fail-closed gate.
2. Проверить worker heartbeat, Bybit connectivity и последние job diagnostics.
3. Проверить `received_at`/`available_at`, candle continuity и instrument spec freshness.
4. После восстановления повторно запустить ingestion; не редактировать confirmed candles вручную.

## `missing_decision_candle` или сигнал на предыдущем часовом окне

1. Не обходить gate увеличением `MAX_CANDLE_AGE_SECONDS`: current-hour signal требует `close_time == event_time`.
2. Проверить ingestion job, последнюю confirmed candle, её `available_at`, `close_time` и worker clock.
3. После появления точной decision candle разрешить обычный idempotent retry; не вставлять свечу и не менять signal natural key вручную.
4. Если версия до 1.9.2 уже опубликовала signal текущего часа по предыдущей свече, сохранить signal/plan snapshots и не считать его пригодным доказательством model quality без отдельного разбора.

## Подозрение на revision confirmed candle

1. Остановить публикацию затронутого symbol/time range.
2. Сохранить внешний payload и текущую строку для расследования.
3. Не выполнять прямой UPDATE подтверждённого OHLCV.
4. До реализации revision quarantine оставить первый confirmed snapshot неизменным и зафиксировать incident.

## Database/migration mismatch

Не запускать штатные процессы до совпадения Alembic head. Использовать backup/restore procedure и отдельную тестовую БД для проверки migration.

Если `python -m alembic heads` показывает одновременно `0008_outcome_path_unavailable` и `0008_plan_outcome_path_unavailable`:

1. не выполнять `upgrade heads`, `stamp` или ручной DDL; обе ветви содержат одинаковое изменение схемы и не должны применяться последовательно;
2. остановить API/worker/trainer и сохранить backup;
3. установить release 1.8.32, где остаётся только `0008_outcome_path_unavailable`;
4. проверить единственный head командой `python -m alembic heads`;
5. выполнить `python manage.py migrate` только после проверки текущей revision.

При падении release 1.8.30 с `StringDataRightTruncation` на записи `0008_plan_outcome_path_unavailable`:

1. не расширять `alembic_version.version_num` вручную и не выполнять `alembic stamp`;
2. проверить `python -m alembic current` — после PostgreSQL transactional rollback ожидается `0007_position_account_scope`;
3. установить 1.8.31 и повторить `python manage.py migrate`;
4. подтвердить head `0008_outcome_path_unavailable` и только затем запускать процессы.

## `INVALID_CAPITAL_PROFILE_POLICY` или предупреждение global risk policy

1. Не принимайте план и не увеличивайте глобальные лимиты только ради снятия блокировки.
2. Сравните профиль с `.env`: `risk_rate <= max_total_risk_rate <= MAX_TOTAL_OPEN_RISK_RATE`, `default_leverage <= max_leverage <= MAX_LEVERAGE`.
3. Исправьте профиль штатным PATCH-запросом/интерфейсом; не редактируйте строку PostgreSQL вручную.
4. Повторно активируйте профиль и убедитесь, что планы пересчитаны с новой `profile_version`.
5. Если уже есть открытые ручные позиции выше нового глобального лимита, не скрывайте превышение: портфельная панель должна оставаться blocked до снижения фактического риска.

## Model incident

Оставить incumbent active, заблокировать candidate activation, проверить hash/task/classes/horizon/calibration, `feature_schema_version`, `label_path_schema_version`, `temporal_split_schema`, `timeout_return_schema_version` и ATR barrier multipliers. Не сравнивать candidate с incumbent при различной barrier geometry; переобучить совместимый artifact или выполнить documented rollback.


## PATH_UNAVAILABLE или подозрительный plan outcome

1. Не трактовать нулевые financial fields как безубыточную сделку: проверить `valuation_status`.
2. Сравнить `plan.sizing_snapshot.planning_time` с `signal.event_time`.
3. Не переиспользовать signal-level TP/SL path для более позднего entry.
4. Для восстановления денежной оценки требуется доказуемый entry-aligned intrabar path; без него оставить запись fail-closed.
5. После migration 0008 проверить число переведённых historical rows и сохранить результат в операционном журнале.
