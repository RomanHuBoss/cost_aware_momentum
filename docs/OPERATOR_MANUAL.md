# Operator Manual

## После обновления на 1.9.5

Migration не требуется. В существующий `.env` можно явно добавить `AUTO_TRAIN_MIN_POLICY_TRADE_RATE=0.01`; при отсутствии переменной применяется тот же безопасный default. Перезапустите trainer/API после замены release tree.

При `quality_gate_failed` проверяйте одновременно `policy_candidates`, `policy_trades`, `policy_trade_rate` и `min_policy_trade_rate`. Причина `policy_trade_rate_below_minimum` означает, что модель на final holdout формирует слишком разреженную исполнимую policy, даже если абсолютное число сделок и их средние результаты выглядят приемлемо. Не снижайте порог только ради активации: сначала проверяйте coverage, data depth, class balance, costs и forward/shadow evidence.

Patch не увеличивает число live-рекомендаций и не обещает доходность. Он предотвращает автоматическую активацию статистически хрупкой модели, которая нашла лишь микроскопическую долю сделок.

## Изменения 1.9.4

Migration и новые `.env`-переменные не нужны. Замените файлы проекта и перезапустите worker/API/trainer штатной командой.

- В diagnostics задания `hourly_market_close` проверяйте `symbols_total`, `symbols_covered`, `requests_failed`, `missing_symbols_sample` и `candle_sync_retry_count`.
- Частичное покрытие вызывает сетевой refetch после cooldown, максимум пять раз. Не увеличивайте лимит и не ослабляйте `missing_decision_candle` только ради появления сигналов.
- Если после лимита `symbols_covered < symbols_total`, проверяйте Bybit connectivity/rate limits, worker clock и фактический payload kline. Следующий час создаёт новый idempotency key и новый цикл.
- Patch повышает шанс получить своевременную точную свечу, но не меняет модель, EV/RR/risk gates и не доказывает прибыльность.

## Запуск

Используйте `manage.py setup`, `configure`, `db-init`, `migrate`, `doctor`, затем `run`. Web UI по умолчанию доступен только на `127.0.0.1:8000`.

## Интерпретация

- Market signal не зависит от капитала профиля.
- Execution plan зависит от капитала, account snapshot, текущего ask/bid, маржи, ликвидности и exchange constraints.
- `BLOCKED`/`NO TRADE` нельзя трактовать как LONG или SHORT.
- `NO_TRADE` с предупреждением о цене вне зоны означает, что market signal существует, но вход по текущей исполнимой цене запрещён.
- `BLOCKED_DATA` при отсутствии bid/ask нельзя обходить использованием last/mark или старой reference price.
- Перед `ACCEPTED` система повторно валидирует freshness, entry-zone, risk, margin, funding, instrument specs и plan version.

## После обновления на 1.9.3

1. Migration и новые `.env`-переменные не требуются; остановите процессы и замените release tree целиком.
2. Проверьте `DEFAULT_RISK_RATE`, `MAX_TOTAL_OPEN_RISK_RATE`, `DEFAULT_LEVERAGE`, `MAX_LEVERAGE` и `MARGIN_RESERVE_RATE` в `.env`.
3. Откройте список профилей. Профиль с общим лимитом выше глобального, с `risk_rate > max_total_risk_rate` или с плечом выше `MAX_LEVERAGE` нельзя активировать; исправьте его PATCH-запросом/интерфейсом до допустимых значений.
4. После изменения/активации профиль пересчитывает текущие планы. План с предупреждением о global risk policy не принимайте и не обходите ручным изменением БД.
5. На панели профилей отображается риск на сделку и общий профильный лимит; портфельная панель добавляет `INVALID_CAPITAL_PROFILE_POLICY` для небезопасного legacy-профиля.

## После обновления на 1.9.2

1. Остановите API, worker и trainer; замените release tree.
2. Выполните `python manage.py release-check` и `python manage.py doctor`.
3. Migration и новые `.env`-переменные отсутствуют; ожидаемый Alembic head остаётся `0009_candle_receipt_availability`.
4. Диагностика `missing_decision_candle` означает, что confirmed candle с `close_time == event_time` ещё не доступна. Не увеличивайте freshness limits и не запускайте ручной вход по предыдущему часовому окну; восстановите ingestion и разрешите штатный retry.
5. Ранее опубликованные сигналы не пересчитываются автоматически. Для анализа подозрительного сигнала сопоставьте `signal.event_time`, `data_cutoff` и последний candle `close_time` в исходном журнале/БД.

## После обновления на 1.9.1

1. Сделайте backup PostgreSQL и остановите API, worker и trainer.
2. Замените release tree и выполните `python manage.py release-check`.
3. Выполните `python manage.py migrate`; ожидаемый head — `0009_candle_receipt_availability`.
4. Перезапустите процессы и выполните `python manage.py doctor`.
5. Учтите: migration намеренно делает legacy candle history недоступной для replay до момента migration. Это не потеря OHLCV, а консервативное исправление неизвестного receipt time.
6. Новых `.env`-переменных и обязательного переобучения нет. Сравнивать research-метрики до и после migration следует только после повторного прогона в одинаковом temporal protocol.

## После обновления на 1.9.0

1. Migration и новые `.env`-переменные не требуются.
2. Остановите API, worker и trainer, замените release tree и выполните `python manage.py release-check`.
3. Старый active artifact без `timeout_return_schema_version=training-direction-median-r-v1` будет отклонён runtime. Это ожидаемый fail-closed результат; не редактируйте artifact и не отключайте проверку.
4. Запустите штатный trainer. Новый candidate должен пересчитать policy evidence schema v10 и пройти существующие absolute/relative gates. Incumbent не считается совместимым benchmark, если его TIMEOUT schema отсутствует.
5. `TIMEOUT_GROSS_RETURN_RATE` не подбирайте для увеличения числа рекомендаций: для нового ML artifact это только baseline fallback. Проверяйте в signal/plan snapshot поля `timeout_gross_return_rate`, `timeout_return_r` и `timeout_return_source`.
6. После activation проведите paper/shadow forward validation с фактическими fills. Техническое исправление EV не доказывает прибыльность и может как увеличить, так и уменьшить число рекомендаций.

## После обновления на 1.8.36

1. Migration и новые `.env`-переменные не требуются.
2. Остановите API, worker и trainer, замените release tree, выполните `python manage.py release-check`, затем перезапустите процессы.
3. Запустите штатное переобучение. Artifact с `label_path_schema_version=ohlc-open-first-stop-gap-v1` теперь несовместим и не должен активироваться вручную.
4. Policy evidence schema v8 пересчитывается как v9. Причина отклонения старого evidence `invalid_policy_metric_schema` после обновления ожидаема.
5. Не снижайте EV/RR/quality gates ради появления рекомендаций: исправление удаляет ложный pre-entry P&L и может сделать результаты более консервативными.

## После обновления на 1.8.35

Migration и новые `.env`-переменные не требуются. Замените файлы, проверьте release manifest и перезапустите API, worker и trainer.

- `not_enough_history_for_bootstrap` — trainer ещё не запускает candidate, потому что configured temporal holdout математически не помещается в доступную hourly history. При defaults требуется 1206 timestamps. Проверьте `history_backfill` в `/api/v1/status`; не уменьшайте gate только ради появления модели.
- `log_loss_skill_vs_prior_not_positive` — candidate на final holdout не лучше class-prior baseline. Такой artifact сохраняется как отклонённый candidate, но не активируется.
- `inconsistent_log_loss_skill_vs_prior` — stored metric не совпадает с `class_prior_log_loss - log_loss`; candidate блокируется как повреждённое evidence.
- Если модель после достаточного backfill всё равно не проходит, нужны реальные candidate metrics и журнал fills. Суточная длительность обучения не является критерием качества.

Исправление предотвращает бессмысленный ранний fit и небезопасную activation, но не обязано увеличивать частоту сигналов. Редкие `NO_TRADE` могут быть корректным результатом fee/slippage/risk/EV gates.

## После обновления на 1.8.34

Migration не требуется. Добавьте в `.env` явно либо примите default `AUTO_TRAIN_MIN_HOLDOUT_SPAN_HOURS=168`, затем перезапустите API, worker и trainer.

- Причина `quality_gate_failed_waiting_for_new_data` означает, что предыдущий детерминированный candidate уже был отклонён и текущий training-data profile не содержит достаточного нового свидетельства. Это штатная защита от бессмысленного ежедневного переобучения; не удаляйте registry/job history и не уменьшайте gate только ради появления сигнала.
- `holdout_span_below_minimum` означает календарно узкий final holdout, даже если строк много из-за большого числа символов. Дождитесь backfill/новых candles.
- `policy_independent_cohort_count_below_minimum` означает недостаток неперекрывающихся label windows. При horizon 8h восемь соседних часовых решений дают примерно одну независимую когорту, а не восемь.
- Policy evidence schema v7 автоматически не переиспользуется; нужен новый candidate, рассчитанный schema v8. Active incumbent не деактивируется из-за отказа candidate.

Эти изменения не создают больше рекомендаций и не доказывают прибыльность. Для диагностики конкретных потерь нужны candidate metrics, signal/plan snapshots и журнал фактических fills.

## После обновления на 1.8.33

1. Migration отсутствует; выполните обычный backup, замените файлы и перезапустите API, worker и trainer.
2. Добавьте в `.env` явные значения `ALLOW_BASELINE_ACTIONABLE=false`, `TIMEOUT_GROSS_RETURN_RATE=-0.002`, `AUTO_TRAIN_MIN_POLICY_COHORTS=20` либо примите совместимые defaults.
3. Если active artifact отсутствует или candidate не проходит gate, baseline-сигналы могут оставаться видимыми, но execution plan должен иметь `NO_TRADE` с предупреждением о diagnostic-only baseline. Не обходите блокировку.
4. В `/api/v1/status` сверяйте `minimum_policy_trades`, `minimum_policy_cohorts`, фактические candidate gate reasons и active model provenance. Суточное обучение само по себе не является основанием снижать запреты.
5. `TIMEOUT_GROSS_RETURN_RATE` нельзя подбирать по тем же данным, на которых оценивается candidate. Для изменения требуется отдельная OOS/forward-калибровка и повторный backtest/promotion evidence.

## После обновления на 1.8.32

1. Сделайте штатный backup PostgreSQL.
2. Замените файлы проекта и выполните `python -m alembic heads`; должен отображаться только `0008_outcome_path_unavailable`.
3. Выполните `python manage.py migrate`, затем `python manage.py doctor`. Новых `.env`-переменных нет.
4. Перезапустите trainer: policy evidence схемы v6 и ниже не используется для promotion; candidate и incumbent будут переоценены с запретом перекрывающихся активных позиций одного символа. Active incumbent из-за ошибки candidate не деактивируется.
5. В research report поле `overlap_blocked_trades` показывает кандидатов, исключённых для соответствия live acceptance. Это не ошибка данных и не следует обходить.

## После обновления на 1.8.31

1. Сделайте штатный backup PostgreSQL.
2. Если migration 1.8.30 уже падала с `StringDataRightTruncation`, не изменяйте таблицу `alembic_version` вручную. Выполните `python -m alembic current`; ожидаемое состояние после транзакционного rollback — `0007_position_account_scope`.
3. Замените файлы проекта на release 1.8.31.
4. Выполните `python manage.py migrate` и убедитесь, что Alembic head — `0008_outcome_path_unavailable`.
5. Перезапустите API, worker и trainer. Новых `.env`-переменных нет.

- `PATH_UNAVAILABLE` означает, что market outcome известен, но план создан позже signal anchor и точный путь от его entry time не сохранён. Нулевые P&L-поля в БД являются техническими placeholders; UI не показывает их как рассчитанный результат. Не заменяйте статус вручную на `VALUED`.
- Migration обнуляет ранее ошибочно оценённые late-plan P&L/R и сохраняет диагностику в `cost_assumptions`.
- После изменения profit-factor semantics candidate/incumbent evidence со schema v5 не подходит для promotion; запустите штатное переобучение/переоценку. Active incumbent не деактивируется из-за ошибки candidate.

## После обновления на 1.8.29

Migration и новые env-переменные не нужны. Перезапустите API, worker и trainer штатной командой.

- Legacy model artifact без `label_path_schema_version` или `temporal_split_schema` теперь блокируется. Не отключайте проверку: переобучите модель текущим trainer и активируйте новый immutable artifact.
- Signal geometry использует точный ATR модели. При очень малом/большом ATR сигнал может стать неисполняемым из-за `tickSize` или невалидной геометрии; это fail-closed поведение.
- Backtest рекомендуется запускать с `--model-sha256 <hash>`, когда hash известен из registry/release evidence.
- `incumbent_barrier_geometry_mismatch` означает, что относительная auto-activation оценка запрещена: модели решают разные barrier-задачи.

## После обновления на 1.8.28

Migration и новые env-переменные не нужны. Перезапустите API/worker/trainer штатной командой.

- Entry-zone теперь состоит только из биржевых тиков, которые реально лежат внутри непрерывного policy-интервала. На инструменте с грубым `tickSize` отображаемая зона может стать уже; если внутри нет исполнимого тика, сигнал блокируется. Не расширяйте границы вручную.
- Private read-only account requests подписываются по точному отправляемому URL. Реальные credentials по-прежнему должны иметь только read-only права.
- По умолчанию `stock`, `forex`, `commodity` и `xstocks` не попадают в криптовалютную вселенную. Не включайте `UNIVERSE_ALLOW_NON_CRYPTO_SYMBOL_TYPES=true` без отдельной валидации модели, издержек, ликвидности и risk limits для этого класса инструментов.

## Ручной вход и reservations

Поле «Комиссия входа, USDT» содержит фактически списанную денежную комиссию, а не процентную ставку. Система заменяет ею модельную entry-комиссию и повторно проверяет фактический stress loss. Вход отклоняется, если он требует больше риска или маржи, чем было зарезервировано принятым планом; пересчитайте план или уменьшите qty.

Для `manual` и `paper` выделенный капитал используется как теоретическая доступная маржа с учётом `margin_reserve_rate`. Уже принятые планы и открытые сделки резервируют эту ёмкость. Для `bybit_read_only` дополнительно резервируются только ещё не исполненные принятые планы, поскольку биржевой available margin уже отражает открытые позиции.
