# Patch 1.6.0 — automatic counterfactual outcomes

## Исправленный пробел

До версии 1.6.0 исходный `MarketSignal` сохранялся независимо от решения оператора, но после завершения горизонта система автоматически не определяла, был ли первым достигнут TP1, SL или TIMEOUT. Для отдельных `ExecutionPlan` не существовало неизменяемого post-event результата. Поэтому отклоненные рекомендации выпадали из оценки, а анализ модели и операторского selection bias требовал ручной реконструкции.

## Решение

- добавлен отдельный hourly worker job `counterfactual_outcomes`;
- исход рассчитывается по непрерывной последовательности confirmed hourly last-price candles от `signal.event_time`;
- для LONG и SHORT применяется направленная геометрия TP1/SL;
- одновременное касание TP1 и SL внутри одного часового бара разрешается консервативно как `SL` с `ambiguous=true`;
- `TIMEOUT` создается только при наличии подтвержденной свечи, закрывающей точный конец горизонта;
- пропуск свечи, неверная геометрия или неполный горизонт не заменяются выдуманным результатом;
- один immutable `SignalOutcome` связывается с исходным сигналом;
- для каждой существующей и позднее созданной версии `ExecutionPlan` создается отдельный immutable `PlanOutcome`;
- plan estimate использует сохраненный qty/risk/cost snapshot, комиссии входа и выхода считаются от соответствующих notional;
- funding учитывает только settlement timestamps, пересеченные гипотетическим периодом удержания, если timeline сохранен в snapshot;
- legacy-планы без проверяемого funding timeline получают `FUNDING_UNAVAILABLE` и не получают фиктивный результат в R;
- unsized-планы получают рыночный outcome, но статус `NOT_SIZED` и без фиктивного R;
- результат добавлен в detail API, вкладку «Экономика», audit chain и transactional outbox.

## Миграция

Добавлена Alembic migration:

```text
0004_counterfactual_outcomes
```

Она создает:

- `advisory.signal_outcomes`;
- `advisory.plan_outcomes`;
- unique constraints по `signal_id` и `plan_id`;
- check constraints для outcome, valuation status, цен и qty;
- индексы для resolution/API lookup.

После обновления выполните:

```bash
python manage.py migrate
```

Downgrade удаляет сначала `plan_outcomes`, затем `signal_outcomes`. Перед downgrade сохраните нужные post-event данные.

## Конфигурация

Новых переменных `.env` нет. Job работает в существующем worker и использует текущий hourly market-data flow.

Новые execution plans сохраняют в `sizing_snapshot.costs`:

- per-settlement funding rate;
- next funding settlement;
- funding interval.

Это обратно совместимое расширение JSONB snapshot. Старые plan rows не переписываются.

## Проверки

Добавлены regression/acceptance tests для:

- LONG TP и SHORT TP;
- same-bar TP/SL ambiguity;
- неполного горизонта и пропуска свечи;
- TIMEOUT по точному horizon close;
- fail-closed directional geometry;
- entry/exit fee notional, slippage, funding и R;
- только реально пересеченных funding settlements;
- legacy funding timeline;
- unsized plans;
- worker/UI wiring.

Полный unit/static post-check указан в `docs/QA_REPORT.md`. PostgreSQL integration tests в среде сборки не выполнялись из-за отсутствия отдельного PostgreSQL server/test database.

## Ограничения

- Outcome относится к первичному TP1/SL/TIMEOUT и не является полным симулятором TP1/TP2, переноса stop и partial fills.
- Часовой OHLC не показывает порядок касаний внутри бара; правило same-bar SL намеренно консервативно.
- Estimated plan P&L не является фактическим P&L ручного исполнения и не заменяет fills journal.
- Funding использует immutable сценарий, сохраненный при создании plan, а не восстановленную фактическую ставку биржи; для legacy snapshot результат в R не публикуется.
- Не реализованы operator latency, no-fill/entry-zone simulation и исторический orderbook impact.

## Rollback

1. Остановить API/worker/trainer.
2. Сделать PostgreSQL backup.
3. Выполнить `python manage.py migrate` на коде 1.5.0 только после Alembic downgrade до `0003_single_active_model`.
4. Вернуть код 1.5.0 и запустить `python manage.py doctor`.

Downgrade необратимо удаляет сохраненные counterfactual outcomes, поэтому предпочтительный rollback — оставить migration 0004 и откатить только worker/API code после проверки совместимости.
