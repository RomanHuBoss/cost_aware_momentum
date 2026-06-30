# Cost-aware hourly ML momentum

> Версия 1.8.12: barrier path учитывает упорядоченный open, opening-gap получает корректные цену/время, а realized policy/backtest/PlanOutcome больше не списывают уже реализованный gap повторно.

Локальная advisory-only система для анализа linear USDT perpetuals Bybit. Она получает рыночные данные, строит часовые признаки, оценивает сценарии LONG/SHORT, учитывает комиссии, проскальзывание, funding, риск и портфельные ограничения и показывает оператору исполнимый план. Приложение не размещает, не изменяет и не отменяет биржевые ордера.

## Основные свойства

- FastAPI API и локальный веб-интерфейс.
- PostgreSQL как единственная база данных.
- Отдельные процессы API, inference worker и trainer.
- Read-only интеграция с Bybit.
- Direction-conditional модель исходов `TP / SL / TIMEOUT`; `NO TRADE` остаётся решением policy layer.
- Runtime возвращает оба directional-сценария; окончательный LONG/SHORT выбирается policy layer по текущим bid/ask, комиссиям, slippage, funding и barrier geometry.
- Immutable model artifacts, SHA-256, candidate/incumbent comparison и guarded activation.
- Decimal-арифметика для денежных и контрактных расчётов.
- Fail-closed при stale/invalid data, несовместимом artifact, нарушенной геометрии, невалидных вероятностях или превышении риска.
- Stateful features (EMA/ATR/rolling statistics) рассчитываются только внутри непрерывного сегмента валидных часовых свечей.
- Принятие плана использует ask для LONG и bid для SHORT, свежий account snapshot и сериализованный общий portfolio-risk check. При неблагоприятном изменении цены внутри entry-zone создается новая версия плана с повторным sizing и net-economics.
- После ручного входа portfolio risk хранит фактический stress loss сделки и пропорционально освобождает его при partial close.
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

По умолчанию проект может использовать динамический universe активных linear-инструментов. `UNIVERSE_MAX_SYMBOLS=0` означает отсутствие искусственного лимита после фильтрации.

## Процессы и данные

### Inference worker

Worker синхронизирует read-only market/account data, instrument specifications, confirmed candles, ticker/funding snapshots и строит рекомендации. Неполные или устаревшие данные блокируют публикацию.

### Trainer

Trainer работает отдельно от API и inference worker. Он:

1. строит point-in-time dataset из confirmed hourly candles;
2. разделяет train/calibration/final holdout по времени;
3. исключает пересечение label horizon с последующим окном;
4. обучает candidate artifact;
5. сравнивает candidate и incumbent на совместимом holdout;
6. активирует candidate только после absolute и relative gates.

### PostgreSQL

SQLite и файлового fallback нет. Изменения схемы применяются только Alembic migrations. Для integration tests используйте отдельную тестовую PostgreSQL-базу.

## Математика риска и стоимости

- LONG приносит положительный gross P&L при `exit > entry`; SHORT — при `exit < entry`.
- `fee_rate_round_trip` означает сумму двух одинаковых ставок комиссии: entry-leg и exit-leg.
- Entry fee считается от entry notional, exit fee — от фактического exit notional.
- Положительный funding: LONG платит, SHORT получает; отрицательный funding меняет знак. В stress downside входит только неблагоприятный funding; благоприятный cash flow учитывается в outcome/EV, но не уменьшает консервативный риск-знаменатель.
- Stop-gap reserve относится к downside.
- Leverage меняет margin requirement, но не экономический edge на notional.
- Quantity округляется вниз по `qtyStep`; после округления повторно проверяются risk, margin, `minQty` и `minNotional`.
- Безопасный размер ниже биржевого минимума блокируется и не округляется вверх.

## Временная семантика ML

Часовой feature row становится доступен только после закрытия исходной свечи. Dataset хранит:

- `source_open_time` — начало исходной свечи;
- `decision_time` — её закрытие и момент доступности признаков;
- `label_end_time` — закрытие последней свечи label horizon.

Train/calibration/final holdout формируются по `decision_time`; labels предыдущего окна обязаны завершиться раньше следующего окна. Stateful features сбрасывают состояние на gap, duplicate или невалидной OHLCV-свече; label-window с нечисловой/некогерентной ценой исключается. Новые artifacts используют `feature_schema_version=hourly-barrier-contiguous-v3` и `temporal_split_schema=decision-and-label-end-purged-v3`.

## Research backtest

Research dataset атомарно создает ровно одну LONG- и одну SHORT-строку на symbol/timestamp; если геометрия хотя бы одного направления невалидна, исключается весь cohort. До выбора направления все строки проверяются на допустимый target, finite barrier/return, exit index и доступность label; поврежденная проигравшая строка не может исчезнуть из проверки. Temporal split, holdout policy и backtest повторно проверяют этот контракт fail-closed. После проверки backtest выбирает не более одного направления по тому же порядку policy, что и production: максимальный net `EV/R`, затем net RR и детерминированный LONG tie-break. Runtime, holdout policy, backtest и Decimal risk math отвергают probabilities вне диапазона `[0, 1]`, с неединичной суммой либо нечисловыми значениями. Комиссия каждой ноги считается от фактического входного/выходного notional; slippage, stop-gap reserve, статический funding-сценарий и policy-пороги задаются отдельно.

Для горизонта `H` часов капитал делится на `H` равных sleeves. Часовой cohort использует один sleeve и этот капитал не переиспользуется до завершения максимального label horizon. Поэтому перекрывающиеся H-часовые returns не компаундятся как последовательные одночасовые сделки и не создают скрытое H-кратное плечо. PnL зачисляется в equity curve в modeled candle exit time. Метрики concurrency считают реально открытые позиции, а не только новые входы в один timestamp.

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


## Обновление с 1.8.11 на 1.8.12

- Новая migration и новые `.env` переменные отсутствуют; Alembic head остается `0006_manual_trade_remaining_risk`.
- Label/outcome path теперь валидирует полный OHLC и разрешает `open` раньше unordered `high/low`: favorable TP gap ограничивается target, adverse SL gap оценивается по open.
- Opening-gap exit получает точное `open_time`, а dataset сохраняет `exit_at_open`; это исключает искусственный сдвиг realized P&L и funding к закрытию свечи.
- Holdout policy, research backtest и PlanOutcome используют realized SL return; stop-gap reserve уменьшается на gap, уже содержащийся в фактической modeled exit price.
- Policy metrics имеют schema `exit-time-realized-gap-horizon-sleeves-v3`, новые counterfactual outcomes — `primary-barrier-intrabar-open-gap-v4`.
- Новые model artifacts сохраняют `label_path_schema_version=ohlc-open-first-stop-gap-v1`; существующие artifacts остаются runtime-совместимыми по features/classes, однако candidate/incumbent и исторические backtest/policy metrics необходимо пересчитать перед сравнением.
- Перезапустите API, worker и trainer; переобучите candidate и пересчитайте research/holdout metrics.

## Обновление с 1.8.10 на 1.8.11

- Новая migration и новые `.env` переменные отсутствуют; существующий Alembic head остается `0006_manual_trade_remaining_risk`.
- Candidate и incumbent необходимо оценивать заново: policy metrics теперь имеют schema `exit-time-horizon-sleeves-v2`, содержат `policy_horizon_hours`/`policy_capital_sleeves`, а drawdown/total R нормализованы по `H` перекрывающимся capital sleeves. Legacy policy metrics не проходят auto-activation gate.
- Execution plan больше не наследует cumulative funding scenario из времени публикации signal: funding повторно проецируется от `planning_time` по последнему ticker/spec. Ненулевой settlement внутри горизонта при неизвестном interval блокирует plan как `BLOCKED_DATA`.
- Fractional/boolean/неположительное leverage не округляется молча; sizing блокируется, liquidation-check отклоняет вход.
- Hourly outcome evaluator принимает только точные одночасовые бары с `low <= close <= high`; intrabar evaluator передает собственный interval. Новые outcomes имеют `evaluation_version=primary-barrier-intrabar-v3`.
- Entry/close manual fills не могут быть naive или датированы будущим временем. HTTP 422 возвращается до изменения журнала.
- Переобучите candidate и пересчитайте исследовательские/policy-метрики перед сравнением с результатами 1.8.10.

## Обновление с 1.8.9 на 1.8.10

- Обязательна migration `0006_manual_trade_remaining_risk`; выполните `python manage.py migrate` до запуска API/worker.
- Новые `.env` переменные не добавлены, но количественные параметры теперь fail-closed отклоняют `NaN`, бесконечность, отрицательные комиссии/slippage/gap reserve, нулевые TTL/age limits и противоречивые risk caps.
- Положительный funding теперь корректно списывается с LONG и начисляется SHORT в live risk math, holdout policy и research backtest. Старые backtest/policy metrics с funding нельзя сравнивать напрямую без перерасчета.
- Active artifact должен содержать точный `feature_schema_version=hourly-barrier-contiguous-v3`, положительный целый `horizon_hours`, непустой `calibration_version`, точный class order и полный finite feature vector. Несовместимый artifact блокируется; переобучите/перерегистрируйте старый artifact вместо обхода проверки.
- При неблагоприятном executable entry внутри разрешенной зоны система создает новую versioned execution plan и пересчитывает qty, risk, RR/EV и liquidation buffer.
- Manual trade хранит `initial_stress_loss` и `remaining_stress_loss`; portfolio open risk использует фактический риск входа и освобождает его пропорционально закрытому количеству.
- Counterfactual PlanOutcome использует entry и planning time immutable plan snapshot, а не исходную цену/время signal.
- Перезапустите API, worker и trainer после migration.

## Обновление с 1.8.8 на 1.8.9

- DB migration и новые `.env` переменные не требуются.
- Перезапустите API, worker и trainer после замены файлов.
- Переобучение рекомендуется: dataset теперь исключает весь symbol/timestamp cohort, если невозможно корректно построить хотя бы один из LONG/SHORT сценариев.
- Temporal split, holdout policy и research backtest теперь fail-closed отклоняют входные данные без точной пары `LONG + SHORT`; ранее односторонние cohorts могли смещать policy metrics и candidate/incumbent comparison.
- Исторические research/holdout metrics, рассчитанные на неполных directional cohorts, не следует объединять с результатами 1.8.9 без повторного расчета.

## Обновление с 1.8.7 на 1.8.8

- DB migration и новые `.env` переменные не требуются.
- Перезапустите API, worker и trainer после замены файлов.
- Переобучение рекомендуется: исправлена реализация уже заявленной strict-hourly feature schema, и строки после восстановленного разрыва больше не наследуют EMA/rolling state из старого сегмента.
- Невалидная OHLCV-свеча в обязательном feature/label window теперь блокирует inference или исключается из dataset вместо clip/timeout fallback.
- Active artifact с probabilities вне TP/SL/TIMEOUT simplex теперь отвергается fail-closed; нормальные calibrated artifacts совместимы.
- Holdout policy metrics `policy_realized_total_r` и `policy_max_drawdown_r` теперь формируются по modeled exit time и equal-weight decision cohorts; старые и новые значения нельзя напрямую объединять.
- Биржевой `max_leverage < 1` считается невалидным instrument constraint и дает `BLOCKED_INVALID_INPUT`, а не молча заменяется на 1x.

## Обновление с 1.8.6 на 1.8.7

- DB migration не требуется.
- Добавлена необязательная переменная `MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS`; безопасный default — `180`. Для явной конфигурации перенесите ее из `.env.example` в локальный `.env`.
- Перезапустите API и worker после замены файлов.
- При `Принять` entry-zone проверяется по текущему ask для LONG и bid для SHORT. `last_price` сохраняется только как диагностика и больше не считается ценой немедленного входа.
- Read-only capital profile блокируется, если snapshot equity/available margin отсутствует, старше лимита либо имеет некорректное время.
- Конкурентные accept-запросы сериализуются глобальным transaction-scoped PostgreSQL advisory lock до чтения open risk и капитала.
- Stop-loss за консервативно оцененной областью ликвидации получает `BLOCKED_LIQUIDATION` при любом плече, включая 1–3x.

## Обновление с 1.8.5 на 1.8.6

- DB migration и новые `.env` переменные не требуются.
- Перезапустите API и worker после замены файлов; trainer можно перезапустить одновременно.
- Неполный `hourly_inference` повторяется до пяти раз с интервалом не меньше `MARKET_POLL_SECONDS`. Уже опубликованные natural keys не дублируются.
- `/api/v1/status` содержит `recommendation_summary`, последний `hourly_inference`, причины отсева и распределение статусов планов активного профиля.
- Раздел «Готовы к входу сейчас» показывает только исполнимые планы, цена которых уже находится в зоне входа; остальные явно распределяются по «Наблюдение», «Без сделки» и «Заблокированные».

## Обновление с 1.8.4 на 1.8.5

- DB migration и новые `.env` переменные не требуются.
- Перезапустите API, worker и trainer после замены файлов.
- Переобучение artifact не требуется: существующие artifacts без barrier multipliers используют совместимые дефолты `1.15 / 2.20`; новые значения из bundle теперь применяются и в live geometry.
- Backtest report меняет экономический смысл `net_return`: вместо почасового компаундинга перекрывающихся полногоризонтных returns используется `H` неперекрывающихся capital sleeves. Старые и новые backtest-метрики нельзя напрямую склеивать в один временной ряд.
- CLI `--minimum-predicted-edge` сохранён как deprecated alias для `--minimum-net-ev-r`; новые запуски должны использовать явное имя EV/R.

## Ограничения

- Нет автоматического исполнения ордеров.
- Ручные fills остаются источником фактической информации об исполнении.
- Техническая корректность расчётов и тестов не означает наличия статистически устойчивого торгового преимущества.
