# Operator Manual

## First training readiness

Default training preflight currently needs at least 1206 label-eligible hourly timestamps, and the purged walk-forward development slice currently needs 366 timestamps after filtering. Release 1.52.7 keeps `INITIAL_BACKFILL_BARS=1500` and adds `HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL=7` so hourly OI context no longer caps the usable development history near 326 timestamps. If your existing `.env` still says `INITIAL_BACKFILL_BARS=1000`, change it to `1500`; if it defines `HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL` below 7, change it to 7. Restart worker/trainer afterward.


## Безопасный запуск

1. Создайте Python environment по требованию `pyproject.toml`.
2. Заполните локальный `.env` по `.env.example`; не помещайте его в архив.
3. Настройте отдельную PostgreSQL database и выполните Alembic migrations.
4. Запустите `python manage.py doctor`.
5. Запускайте API, inference worker и trainer отдельными процессами через предусмотренные команды `manage.py`.

## Работа с рекомендациями

- Проверяйте freshness, direction, entry zone, execution status, costs, funding и warnings.
- `ACCEPTED` означает только решение оператора; ордер на биржу не создаётся.
- Реальный вход и выход регистрируются вручную в fills/trades journal.
- Не обходите `NO_TRADE`, stale, risk, margin, liquidity, reconciliation или model quarantine блокировки.



## Обновление 1.52.8

Если trainer показывает `RUNNING`, активна `baseline-momentum-v1`, а последняя попытка завершилась ошибкой `No direction-specific barrier labels could be built from PostgreSQL candles`, это означает, что текущий PostgreSQL market-data slice не дал пригодного direction-specific набора labels `TP / SL / TIMEOUT` для LONG/SHORT scenarios. В 1.52.8 диалог trainer больше не показывает общее `Trainer еще не сообщил причину ожидания`, когда такая ошибка уже сохранена в `model_retraining` job; он выводит derived `effective_wait_reason` и последнюю ошибку.

Действия оператора: не включайте baseline как доказательство качества модели и не ослабляйте gates. Дождитесь backfill/funding/mark/index/OI/spec context либо перезапустите trainer после завершения backfill. Если ошибка повторяется на достаточной истории, проверьте `recent_jobs`, `data_quality_issues` и coverage market context в PostgreSQL.

Повторные `Catch-up inference skipped because publication window is stale` для одного `reason + event hour` теперь подавляются после первого terminal skip. Следующий час остаётся eligible; `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS` не увеличен.

## Обновление 1.52.7

Миграций нет. Добавлена новая `.env` variable `HISTORY_BACKFILL_OPEN_INTEREST_PAGES_PER_SYMBOL=7`; отсутствующее значение безопасно берётся из default, но при явном меньшем значении в локальном `.env` trainer может снова показать `insufficient_walk_forward_history_after_filtering`.

Если в логах есть `actual_timestamps=326, required_timestamps=366`, сначала проверьте `history_backfill.open_interest_history.progress`: старый 2-page OI cap давал около 400 raw hourly OI rows и не покрывал текущий walk-forward development contract. Не снижайте folds/purge/holdout; увеличьте OI history depth и дайте worker завершить backfill.

Повторяющиеся `Hourly decision cycle skipped because publication window is stale` для одного и того же event hour теперь подавляются после первого terminal skip. Сам `decision_publication_lag_exceeded` остается правильной fail-closed блокировкой; устаревший hourly signal публиковать нельзя.

После обновления перезапустите worker и trainer.

## Обновление 1.52.5

Миграций и новых `.env` variables нет. После обновления перезапустите trainer и API/UI process.

Если предыдущий bootstrap/recovery candidate не прошёл quality gate, а его training profile был сохранён только в `metrics`, окно trainer теперь всё равно показывает ожидание новых размеченных часов вместо общей защитной паузы. Поле `previous_profile_source` может быть `trigger.training_data_profile` или `metrics.training_data_profile`; оба источника являются persisted job evidence. Если профиль отсутствует в обоих местах, scheduler сохраняет generic cooldown и не делает недоказанный вывод о данных.

## Обновление 1.52.4

Миграций и новых `.env` variables нет. После обновления перезапустите trainer и API/UI process.

Если при активной `baseline-momentum-v1` UI показывает `quality_gate_failed_waiting_for_new_data`, предыдущий candidate был построен, но не прошёл quality gate; повтор до накопления новых размеченных часов обычно снова будет заблокирован тем же gate. Если отображается `training_deferred_waiting_for_new_data`, после feature/context/label filtering или walk-forward capacity не хватило пригодной истории. В обоих случаях смотрите progress bar «Новые размеченные часы» и `AUTO_TRAIN_MIN_NEW_TIMESTAMPS`; recovery не отключает temporal validation, quality gate и fail-closed защиту active model.

NumPy в release contract ограничен `<2.5`; при обновлении environment переустановите зависимости по `pyproject.toml`, чтобы не подтянуть несовместимый NumPy 2.5.x.

## Обновление 1.52.3

Миграций и новых `.env` variables нет. После обновления перезапустите inference worker.

Если видите `decision_publication_lag_exceeded`, это означает, что сигнал за текущий hourly event time уже опоздал относительно `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS`; worker теперь не пытается публиковать такой stale signal и фиксирует terminal skip. Не увеличивайте лимит ради появления рекомендаций: сначала проверьте, почему market/backfill/drift/startup jobs заняли больше допустимого окна. Следующий eligible hour должен обрабатываться штатно.

## Обновление 1.52.2

Миграций и новых `.env` variables нет. После обновления перезапустите API и inference worker.

Execution plan теперь ограничивает размер quantity-safe глубиной стакана: суммарный quote notional нескольких уровней не переводится обратно в завышенный base quantity по одной цене. При принятии плана fresh FULL-fill VWAP может находиться между тиками, если каждый исходный уровень и signal geometry соответствуют tick size. `PARTIAL`/`NO_FILL`, stale snapshot, выход за entry zone, ухудшение цены, risk, funding, margin и reconciliation по-прежнему блокируют acceptance.

## Обновление 1.52.1

Миграций и новых `.env` variables нет. После обновления перезапустите worker и trainer.

Если raw history прошла preflight, но после feature/context/label filtering её недостаточно для purged walk-forward, trainer теперь показывает healthy `WAITING` и результат `DEFERRED`, а не `ERROR`. Поле `walk_forward_capacity` показывает фактические и минимально необходимые development timestamps. Не снижайте folds/purge/holdout: дождитесь новых данных и устраните gaps/missing point-in-time evidence.

Warning `Signal publication blocked by decision-time execution contract` теперь обязан содержать `reason_code`, `contract_error`, event/publish timestamps, lag и configured limit. При mismatch сравните artifact/runtime entry-zone и publication-delay values; при lag устраните задержку decision pipeline. Публикация остаётся заблокированной до совпадения контракта.

## Обновление 1.52.0

Миграций нет. Новые bootstrap-параметры уже имеют безопасные defaults в `.env.example`. После обновления перезапустите worker и trainer. В окне trainer ожидайте режим `historical_frozen_dynamic_bootstrap`; счётчик истории должен начать отражать загруженные historical hours, а не только часы после установки. После накопления полной prospective history режим автоматически сменится на `prospective_dynamic_replay`.

До запуска выполните:

```bash
python manage.py release-check
python -m pip check
python -m pytest -q
```

Для сборки нового release сначала удалите caches/build artifacts, затем выполните `release-check --write` и повторную verification.
