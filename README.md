# Cost-aware hourly ML momentum

> Версия 1.9.0: TIMEOUT больше не получает одну глобальную доходность −0,2%. Trainer оценивает устойчивую direction-conditional TIMEOUT-доходность в единицах stop-risk только на train window; тот же immutable результат используется в holdout policy, live signal, execution plan и acceptance.

Локальная advisory-only система для анализа linear USDT perpetuals Bybit. Она получает рыночные данные, строит часовые признаки, оценивает сценарии LONG/SHORT, учитывает комиссии, проскальзывание, funding, риск и портфельные ограничения и показывает оператору исполнимый план. Приложение не размещает, не изменяет и не отменяет биржевые ордера.

## Основные свойства

- FastAPI API и локальный веб-интерфейс.
- PostgreSQL как единственная база данных.
- Отдельные процессы API, inference worker и trainer.
- Read-only интеграция с Bybit.
- Direction-conditional модель исходов `TP / SL / TIMEOUT`; `NO TRADE` остаётся решением policy layer.
- Runtime возвращает оба directional-сценария; окончательный LONG/SHORT выбирается policy layer по текущим bid/ask, комиссиям, slippage, funding и barrier geometry.
- Immutable model artifacts, SHA-256, candidate/incumbent comparison и guarded activation.
- Promotion gate отдельно проверяет raw trades, неперекрывающиеся по label horizon временные когорты и минимум 168 часов holdout; число символов не заменяет временную глубину.
- До запуска bootstrap trainer вычисляет необходимую часовую историю из feature warm-up, horizon, temporal split и holdout gates. При defaults требуется не менее 1206 уникальных часовых timestamps; это необходимое, но не достаточное условие при гэпах/невалидных свечах.
- Кандидат обязан иметь строго положительный `log_loss_skill_vs_prior`; модель хуже простого class-prior прогноза не может быть auto-activated даже при прохождении абсолютного `log_loss` лимита.
- После `quality_gate_failed` bootstrap/recovery повторяется только при достаточном числе новых timestamps или материальном изменении training-data profile; operator recovery остаётся явным override.
- Decimal-арифметика для денежных и контрактных расчётов.
- Market-signal economics остается независимой от капитала; account-dependent execution-plan economics пересчитывается отдельно и проверяется по immutable snapshot перед показом.
- Fail-closed при stale/invalid data, несовместимом artifact, нарушенной геометрии, невалидных вероятностях или превышении риска.
- Некалиброванный baseline может формировать диагностический market signal, но по умолчанию не создаёт исполнимый план и не может быть принят оператором.
- Для ML artifacts TIMEOUT gross return оценивается отдельно для LONG/SHORT как медиана train-only TIMEOUT returns в единицах stop-risk и масштабируется к текущей barrier geometry. `TIMEOUT_GROSS_RETURN_RATE` остаётся явным fallback только для baseline/legacy diagnostic paths; опубликованный signal сохраняет фактически использованное значение, и plan/acceptance не пересчитывают его из текущего `.env`.
- Stateful features (EMA/ATR/rolling statistics) рассчитываются только внутри непрерывного сегмента валидных часовых свечей.
- Принятие плана использует ask для LONG и bid для SHORT, свежий account snapshot и сериализованный account/profile-scoped portfolio-risk check. Перед `ACCEPTED` заново проверяются per-trade risk, доступная маржа, полная funding timeline, account reconciliation, текущий turnover-based liquidity cap, `tickSize`/`qtyStep`/min-order/max-leverage ограничения и net policy economics; изменившиеся входы создают новую версию плана.
- Для manual/paper-профилей выделенный капитал одновременно задаёт теоретическую доступную маржу; margin reserve применяется до расчёта размера позиции. Уже принятые планы и открытые manual/paper-сделки уменьшают доступную маржинальную ёмкость; для read-only аккаунта открытые позиции повторно не вычитаются из биржевого available margin.
- При ручном входе фактическая комиссия в USDT заменяет модельную entry-комиссию. Запись блокируется, если фактический stress loss или margin requirement превышает reservation принятого плана. После входа portfolio risk хранит фактический stress loss сделки и пропорционально освобождает его при partial close.
- Нативный запуск без Docker, Redis и Celery.

## Требования

- Python 3.12 или новее.
- PostgreSQL 16 или 17.
- `psql`, `pg_dump` и `pg_restore` в `PATH`.
- Доступ к интернету для установки зависимостей и чтения данных Bybit.
- Node.js нужен только для дополнительной проверки синтаксиса frontend-кода.

## Быстрый запуск на Windows

Откройте PowerShell в каталоге проекта:

```powershell
py -3.12 manage.py setup
py -3.12 manage.py configure
py -3.12 manage.py db-init
py -3.12 manage.py migrate
py -3.12 manage.py doctor
py -3.12 manage.py run
```

После запуска откройте `http://127.0.0.1:8000`.

## Быстрый запуск на Linux/macOS

```bash
python3.12 manage.py setup
python3.12 manage.py configure
python3.12 manage.py db-init
python3.12 manage.py migrate
python3.12 manage.py doctor
python3.12 manage.py run
```

При peer-аутентификации PostgreSQL базу можно создать отдельно системным пользователем `postgres`, затем выполнить `python3.12 manage.py migrate`.

## Основные команды

```text
python manage.py setup          создать .venv и установить зависимости
python manage.py configure      создать SECRET_KEY и настроить оператора
python manage.py db-init        создать прикладную роль и PostgreSQL-базу
python manage.py migrate        применить Alembic migrations
python manage.py doctor         проверить окружение и migration head
python manage.py run            запустить API, worker и trainer
python manage.py api            запустить только API
python manage.py worker         запустить только inference worker
python manage.py trainer        запустить только trainer
python manage.py test           запустить тесты
python manage.py lint           выполнить Ruff
python manage.py backup         создать PostgreSQL backup
python manage.py restore-check  проверить backup восстановлением
python manage.py report         сформировать ежедневный отчёт
python manage.py release-check  проверить release tree и SHA256SUMS
```

## Конфигурация

`manage.py configure` создаёт локальный `.env`. Реальные credentials не должны попадать в архив или систему контроля версий. Шаблон переменных находится в `.env.example`.

Поддерживаются оба формата списков:

```env
SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT
HORIZONS_HOURS=4,8,12
```

и

```env
SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT"]
HORIZONS_HOURS=[4,8,12]
```

По умолчанию проект может использовать динамический universe активных linear-инструментов. `UNIVERSE_MAX_SYMBOLS=0` означает отсутствие искусственного лимита после фильтрации. Криптовалютная модель исключает известные Bybit `symbolType` для TradFi-продуктов (`stock`, `forex`, `commodity`, `xstocks`/`xstock`); явный opt-in возможен только через `UNIVERSE_ALLOW_NON_CRYPTO_SYMBOL_TYPES=true`.

## Процессы и данные

### Inference worker

Worker синхронизирует read-only market/account data, instrument specifications, confirmed candles, ticker/funding snapshots и строит рекомендации. Неполные или устаревшие данные блокируют публикацию.

Для point-in-time целостности время получения внешнего ответа фиксируется после завершения соответствующего API-вызова. Открытая свеча может обновляться до первого подтверждённого снимка; уже подтверждённая свеча считается неизменяемым рыночным фактом и не перезаписывается без отдельной аудируемой revision policy. Inference отдельно ограничивает рыночное время данных (`market cutoff`) и момент фактического решения (`availability cutoff`).

### Trainer

Trainer работает отдельно от API и inference worker. Он:

1. строит point-in-time dataset из confirmed hourly candles;
2. разделяет train/calibration/final holdout по времени;
3. исключает пересечение label horizon с последующим окном;
4. обучает candidate artifact;
5. сравнивает candidate и incumbent только на совместимом holdout с одинаковыми horizon, label semantics, temporal split и ATR barrier geometry;
6. активирует candidate только после absolute и relative gates.

### PostgreSQL

SQLite и файлового fallback нет. Изменения схемы применяются только Alembic migrations. Для integration tests используйте отдельную тестовую PostgreSQL-базу.

## Математика риска и стоимости

- LONG приносит положительный gross P&L при `exit > entry`; SHORT — при `exit < entry`.
- `fee_rate_round_trip` означает сумму двух одинаковых ставок комиссии: entry-leg и exit-leg.
- Entry fee считается от entry notional, exit fee — от фактического exit notional. После фактического входа модельная entry fee заменяется введённой оператором денежной комиссией в USDT; future exit fee остаётся оценкой по stop notional.
- Положительный funding: LONG платит, SHORT получает; отрицательный funding меняет знак. В stress downside входит только неблагоприятный funding; благоприятный cash flow учитывается в outcome/EV, но не уменьшает консервативный риск-знаменатель.
- Stop-gap reserve относится к downside.
- Leverage меняет margin requirement, но не экономический edge на notional. Снижение плеча не считается автоматически безопасным: если оно увеличивает фактическую маржу выше reservation принятого плана, ручной вход блокируется.
- Quantity округляется вниз по `qtyStep`; после округления повторно проверяются risk, margin, `minQty` и `minNotional`.
- Безопасный размер ниже биржевого минимума блокируется и не округляется вверх.
- Funding settlement anchor, даже если он сильно устарел или повреждён, переносится к горизонту арифметически; worker не выполняет цикл по каждому пропущенному settlement.

## Контрфактические исходы

Market outcome `TP / SL / TIMEOUT` вычисляется по пути от `signal.event_time`. Денежная оценка execution plan допустима только когда `plan.planning_time` совпадает с этим якорем. Более поздняя версия плана получает `PATH_UNAVAILABLE`: её qty и связь с market outcome сохраняются, но gross/net P&L и R не вычисляются, поскольку в базе нет точного ценового пути от фактического времени планирования. Это предотвращает ретроактивное использование движения цены, произошедшего до появления плана. Для полноценной оценки поздних планов требуется отдельное хранение entry-aligned intrabar path.

## Временная семантика ML

Часовой feature row становится доступен только после закрытия исходной свечи. Dataset хранит:

- `source_open_time` — начало исходной свечи;
- `decision_time` — её закрытие и момент доступности признаков;
- `label_end_time` — закрытие последней свечи label horizon.

Train/calibration/final holdout формируются по `decision_time`; labels предыдущего окна обязаны завершиться раньше следующего окна. Stateful features сбрасывают состояние на gap, duplicate или невалидной OHLCV-свече; label-window с нечисловой/некогерентной ценой исключается. Исполнимый proxy входа — `open` первой часовой свечи, начинающейся в `decision_time`; барьеры центрируются на этой цене и масштабируются сохранённым `atr_pct_14`, как в live signal policy. Поэтому движение между закрытием feature-свечи и первым доступным входом не используется как контрфактический P&L. Новые artifacts используют `feature_schema_version=hourly-barrier-contiguous-v3`, `label_path_schema_version=decision-open-entry-ohlc-path-v2` и `temporal_split_schema=decision-and-label-end-purged-v3`. Runtime требует точного совпадения всех трёх схем; legacy artifacts нужно переобучить.

## Research backtest

Backtest загружает artifact через тот же runtime validator, что и production; при необходимости `--model-sha256` фиксирует ожидаемый hash. Research dataset атомарно создает ровно одну LONG- и одну SHORT-строку на symbol/timestamp и сохраняет `entry_price` для аудита; если геометрия хотя бы одного направления невалидна, исключается весь cohort. До выбора направления все строки проверяются на допустимый target, finite barrier/return, exit index и доступность label; поврежденная проигравшая строка не может исчезнуть из проверки. Temporal split, holdout policy и backtest повторно проверяют этот контракт fail-closed. После проверки backtest выбирает не более одного направления по тому же порядку policy, что и production: максимальный net `EV/R`, затем net RR и детерминированный LONG tie-break. Runtime, holdout policy, backtest и Decimal risk math отвергают probabilities вне диапазона `[0, 1]`, с неединичной суммой либо нечисловыми значениями. Комиссия каждой ноги считается от фактического входного/выходного notional; slippage, stop-gap reserve, статический funding-сценарий и policy-пороги задаются отдельно. Без timestamp фактического выхода статический funding учитывается только в неблагоприятную сторону: выгодный платеж не улучшает RR/EV или backtest PnL, поскольку позиция могла закрыться до settlement.

Для горизонта `H` часов капитал делится на `H` равных sleeves. Часовой cohort использует один sleeve и этот капитал не переиспользуется до завершения максимального label horizon. Средние promotion-метрики рассчитываются сначала внутри каждого hourly cohort, затем одинаково по cohort timestamps; количество символов в одном часу не создает дополнительные независимые наблюдения. Auto-activation требует минимум как raw trades, так и независимых `policy_cohorts`. Gross gain и gross loss для profit factor суммируются по отдельным trade contributions до агрегации по времени выхода; одновременные прибыль и убыток не взаимопогашаются. Положительный holdout без отрицательных trade contributions представляет profit factor как математически неограниченный только при явных `gross_gain > 0` и `gross_loss = 0`; отсутствие сделок или неполные метрики остаются fail-closed. Дополнительно research-поток применяет live-инвариант «не более одного активного плана на symbol в одном account scope»: следующий кандидат того же символа исключается до modeled exit предыдущего, а вход ровно на границе выхода разрешён. Число исключённых кандидатов публикуется как `overlap_blocked_trades` / `policy_overlap_blocked_trades`. Поэтому перекрывающиеся H-часовые returns не компаундятся как последовательные одночасовые сделки, не создают скрытое H-кратное плечо и не завышают promotion evidence сделками, которые live acceptance отклонил бы. PnL зачисляется в equity curve в modeled candle exit time. Метрики concurrency считают реально открытые позиции, а не только новые входы в один timestamp.

`net_return` сохраняет консервативный stop-gap reserve на SL только в части, еще не встроенной в наблюдаемую gap-цену выхода; рядом выводится `net_return_without_stop_gap_reserve`, чтобы отделить остаточный риск-буфер от результата без него.

Research backtest не моделирует intrahorizon mark-to-market, полный historical order book, entry-zone/no-fill, partial fills, фактическую funding timeline и задержку оператора и не является доказательством прибыльности.

## Режимы

- `paper` — виртуальный капитал и ручная регистрация сделок;
- `shadow` — реальные рыночные сигналы без исполнения;
- `production` — advisory-only;
- `backtest` — исследовательские CLI-процессы.

## Тесты

Обычная проверка:

```bash
python -m pip check
python -m compileall -q app scripts tests manage.py
python -m ruff check .
python -m pytest -q
node --check web/js/app.js
python manage.py release-check
```

PostgreSQL integration tests:

```bash
python manage.py test --require-integration
```

Не направляйте integration tests в production-базу. Задайте `TEST_DATABASE_URL` либо временно `POSTGRES_ADMIN_URL`, чтобы test runner создал отдельную базу.


## Ограничения

- Нет автоматического исполнения ордеров.
- Ручные fills остаются источником фактической информации об исполнении.
- Техническая корректность расчётов и тестов не означает наличия статистически устойчивого торгового преимущества.
