# Operator Manual

## Запуск

Используйте `manage.py setup`, `configure`, `db-init`, `migrate`, `doctor`, затем `run`. Web UI по умолчанию доступен только на `127.0.0.1:8000`.

## Интерпретация

- Market signal не зависит от капитала профиля.
- Execution plan зависит от капитала, account snapshot, текущего ask/bid, маржи, ликвидности и exchange constraints.
- `BLOCKED`/`NO TRADE` нельзя трактовать как LONG или SHORT.
- `NO_TRADE` с предупреждением о цене вне зоны означает, что market signal существует, но вход по текущей исполнимой цене запрещён.
- `BLOCKED_DATA` при отсутствии bid/ask нельзя обходить использованием last/mark или старой reference price.
- Перед `ACCEPTED` система повторно валидирует freshness, entry-zone, risk, margin, funding, instrument specs и plan version.

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
