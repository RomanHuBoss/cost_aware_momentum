# Incident runbook

## Общий принцип

При сомнении система должна перейти в fail-closed: новые рекомендации не исполняются, существующие записи и audit trail сохраняются.

## PostgreSQL недоступен

1. Остановить API и worker; не включать SQLite.
2. Проверить состояние системной службы PostgreSQL через Services.msc, `Get-Service` либо `systemctl status postgresql`.
3. Проверить доступность `localhost:5432`, свободное место на диске, PostgreSQL logs и права каталога данных.
4. Проверить подключение командой `psql` с параметрами из `DATABASE_URL`.
5. После восстановления выполнить `python manage.py migrate`, `python manage.py doctor` и проверить `/health/ready`.
6. При повреждении восстановить последний `pg_dump`, затем выполнить `python manage.py restore-check` на отдельной временной базе.

## Migration mismatch

API завершится до readiness. Не использовать `stamp head` без проверки. Выполнить резервную копию, `python manage.py migrate`, затем перезапустить API и worker.

## API или worker завершился

1. Запустить соответствующий процесс отдельно через `python manage.py api` или `python manage.py worker`, чтобы увидеть traceback.
2. Проверить `.env`, PostgreSQL connectivity и права записи в `models`, `reports`, `backups`.
3. Запустить `python manage.py doctor`.
4. Проверить `ops.service_heartbeats` и `ops.job_runs`.
5. После исправления перезапустить оба процесса через `python manage.py run` или штатный менеджер служб ОС.

## Stale market data / API lag

1. Не принимать планы с `BLOCKED_STALE_DATA`.
2. Проверить internet/DNS, Bybit status, server time и rate-limit errors.
3. Сравнить последнюю confirmed candle и ticker source time.
4. После восстановления дождаться успешного market job и нового plan version.

## Counterfactual outcome остается pending

1. Проверить `ops.job_runs` для job `counterfactual_outcomes` и поле `intrabar_sync.errors`.
2. Убедиться, что hourly path непрерывен и требуемый 1/3/5-минутный window полностью сохранен в `market.candles` с `confirmed=true`.
3. Проверить доступность public Bybit kline endpoint и отсутствие rate-limit/timeout ошибок.
4. Не записывать TP/SL вручную и не менять существующие outcome rows: после восстановления worker повторит точечную загрузку на следующем cycle.
5. При большом backlog временно увеличить `OUTCOME_INTRABAR_MAX_WINDOWS_PER_CYCLE`, контролируя API rate limits и время job.

## Удален файл active-модели

1. В non-production с `ALLOW_BASELINE_MODEL=true` перезапустить проект обычной командой `python manage.py run`. Worker должен остаться запущенным, а `/api/v1/status` показать baseline runtime, `model_notice.code=ACTIVE_MODEL_ARTIFACT_MISSING` и heartbeat `DEGRADED`.
2. Не удалять stale registry row вручную: он нужен для optimistic activation и аудита.
3. Проверить trainer heartbeat и последний `model_retraining`. При следующем допустимом цикле trainer использует bootstrap recovery; новый candidate должен пройти абсолютные quality gates.
4. Если candidate проходит gates, activation атомарно заменит stale active row. Если нет, baseline остается активным, а candidate регистрируется inactive с причинами gate.
5. Если ошибка относится к SHA256 mismatch, поврежденному bundle, version/schema/classes/horizon mismatch или `ACTIVE_MODEL_PATH`, fallback намеренно не применяется. Восстановить правильный artifact или явно активировать проверенную registry version.
6. В production baseline recovery запрещен: восстановить artifact из доверенной резервной копии либо активировать другую проверенную модель.

## Ошибка модели или drift

1. Деактивировать артефакт: очистить `ACTIVE_MODEL_PATH` и, только для paper/shadow, разрешить baseline.
2. Для production установить `ALLOW_BASELINE_MODEL=false`, чтобы inference был заблокирован.
3. Зафиксировать model hash, feature schema, calibration version и affected signal IDs.
4. Пометить ошибочные сигналы `INVALIDATED`; не удалять их.
5. Выполнить replay и повторную OOS-проверку до активации новой версии.

## Расхождение позиции

1. Запретить новые сделки по конфликтующему символу.
2. Сравнить manual trade journal с read-only Bybit positions/fills.
3. Добавить корректирующую запись, не переписывая исходный fill.
4. Зафиксировать `RECONCILIATION_MISMATCH` в audit.

## Компрометация ключа

1. Немедленно отозвать ключ на Bybit.
2. Проверить, что у ключа не было trading/withdrawal permissions.
3. Заменить `.env`, `SECRET_KEY`, API token и операторский пароль.
4. Просмотреть audit access и логи reverse proxy.
5. Никогда не помещать секреты в issue, model artifact, backup manifest или frontend.

## Trainer создал `.joblib`, но candidate отсутствует в registry

1. Сопоставить время файла в `models/` с последним `ops.job_runs` для `model_retraining`.
2. Если ошибка содержит `InvalidTextRepresentation`, `-Infinity`, `Infinity` или `NaN`, обновить проект минимум до 1.7.1 и перезапустить trainer.
3. Не активировать orphan artifact прямым изменением PostgreSQL и не создавать registry row вручную: same-holdout gate и audit могли не завершиться.
4. Дождаться следующего штатного training cycle. Отклоненный candidate должен появиться в `model-registry list` с `active=false`; прошедший gate может активироваться автоматически.
5. Старый orphan artifact можно оставить для forensic review либо удалить после подтверждения нового зарегистрированного candidate.

## Baseline работает, но recovery training не стартует

1. Проверить `/api/v1/status` и trainer heartbeat. Для отсутствующего active artifact ожидается pending trigger `bootstrap_recovery`; для отсутствующей active registry row или active baseline — `bootstrap_training`.
2. Убедиться, что прошел `AUTO_TRAIN_INITIAL_DELAY_SECONDS`, история содержит минимум bootstrap timestamps, а coverage не ниже `AUTO_TRAIN_MIN_SYMBOL_COVERAGE_RATIO`.
3. В версии 1.7.3 несвязанный старый `scheduled_retraining`/`material_training_dataset_change` failure не должен блокировать новый bootstrap episode.
4. Если предыдущая попытка того же bootstrap/recovery episode завершилась технической ошибкой, ждать только `AUTO_TRAIN_RECOVERY_RETRY_MINUTES` (default 15), а не общий `AUTO_TRAIN_RETRY_HOURS`.
5. Если candidate успешно обучен, но отклонен quality gate, baseline сохраняется, а следующая попытка использует controlled data-change cooldown; не снижать gate ради появления active-модели.
## Counterfactual plan outcome имеет `INVALID_INPUT`

1. Открыть detail конкретной plan version и зафиксировать `plan_id`, `plan_version` и `validation_error` из `cost_assumptions`/audit.
2. Проверить immutable `execution_plans.qty`, `actual_stress_loss` и `sizing_snapshot.costs` на `NaN`, `Infinity`, отрицательные fees/reserves, malformed funding timestamp/interval.
3. Не изменять существующий `plan_outcome`: он является audit-результатом фактического snapshot. Исправить источник данных или import pipeline.
4. Создать новую plan version штатным recalculation только если исходный market signal еще актуален; старую версию не переписывать.
5. После обновления до 1.7.6 убедиться, что `python manage.py migrate` применил head `0005_plan_outcome_invalid_input`.
6. Если invalid относится к entry/exit market outcome, worker оставляет valuation незаписанной и показывает запись в `invalid_plan_outcomes`; исправить corrupted signal/outcome row до повторного запуска.

