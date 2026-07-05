# Cost-aware hourly ML momentum

> Версия 1.23.0: production calibration drift использует только исходы сигналов, чей полный trading horizon уже завершён. Ранние TP/SL незрелых сигналов исключаются, отсутствие outcome у зрелого сигнала блокирует calibration evidence, а отчёт раскрывает maturity coverage. Миграция, новые `.env`-параметры и переобучение artifact не требуются.

Локальная advisory-only система для анализа linear USDT perpetuals Bybit. Она получает рыночные данные, строит часовые признаки, оценивает сценарии LONG/SHORT, учитывает комиссии, проскальзывание, funding, риск и портфельные ограничения и показывает оператору исполнимый план. Приложение не размещает, не изменяет и не отменяет биржевые ордера.

## Основные свойства

- FastAPI API и локальный веб-интерфейс.
- PostgreSQL как единственная база данных.
- Отдельные процессы API, inference worker и trainer.
- Read-only интеграция с Bybit.
- Direction-conditional модель исходов `TP / SL / TIMEOUT`; `NO TRADE` остаётся решением policy layer.
- Artifact model использует 10 OHLCV-derived и 7 point-in-time market-context features: OI momentum, mark/index basis, settled funding state и turnover/OI liquidity proxy. Точный OI/basis и свежий funding anchor обязательны; zero-fill и future event leakage запрещены.
- Runtime возвращает оба directional-сценария; окончательный LONG/SHORT выбирается policy layer по текущим bid/ask, комиссиям, slippage, funding и barrier geometry.
- Immutable model artifacts, SHA-256, candidate/incumbent comparison и guarded activation.
- Production drift monitoring сравнивает только активную model version с её immutable final-holdout reference: feature/probability PSI, coverage/missingness, maturity-corrected selected-direction calibration и actionability density. Ранние barrier outcomes до полного horizon не входят в calibration; unresolved mature outcomes блокируют evidence. `CRITICAL/BLOCKED` деградирует operational heartbeat; automatic model action намеренно отсутствует.
- Research experiment-selection governance prospectively учитывает все backtest-конфигурации одной family, включая failed/open attempts; по выровненным почасовым return paths считает CSCV/PBO, HAC-adjusted Deflated Sharpe и moving-block confidence intervals. Неполный ledger или недостаток независимых временных блоков даёт `BLOCKED`, а не оптимистичную оценку.
- Formal experiment-family preregistration фиксирует гипотезу, точный cohort fingerprint/horizon, полный search space, primary metric, thresholds, stopping budget/deadline и допустимые exclusion criteria до первого `STARTED`. Trial вне контракта не вычисляется.
- Promotion gate отдельно проверяет raw trades, неперекрывающиеся по label horizon временные когорты и минимум 168 часов final holdout; число символов не заменяет временную глубину. До final holdout candidate обязан пройти три последовательных purged expanding walk-forward folds с независимым переобучением и калибровкой.
- Экономический promotion gate использует не только point mean R, но и 95% one-sided lower confidence bound. Для горизонта `H` часов отдельно оцениваются все `H` неперекрывающихся часовых фаз; gate использует худшую фазовую LCB и требует полного покрытия фаз. Default требует `LCB > 0`.
- До запуска bootstrap trainer вычисляет необходимую часовую историю из feature warm-up, horizon, temporal split и holdout gates. При defaults требуется не менее 1206 уникальных часовых timestamps; это необходимое, но не достаточное условие при гэпах/невалидных свечах.
- Кандидат обязан иметь строго положительный `log_loss_skill_vs_prior`; модель хуже простого class-prior прогноза не может быть auto-activated даже при прохождении абсолютного `log_loss` лимита.
- После `quality_gate_failed` bootstrap/recovery повторяется только при достаточном числе новых timestamps или материальном изменении training-data profile; operator recovery остаётся явным override.
- Decimal-арифметика для денежных и контрактных расчётов.
- Market-signal economics остается независимой от капитала; account-dependent execution-plan economics пересчитывается отдельно и проверяется по immutable snapshot перед показом.
- Fail-closed при stale/invalid data, несовместимом artifact, нарушенной геометрии, невалидных вероятностях или превышении риска.
- Глобальные `MAX_TOTAL_OPEN_RISK_RATE` и `MAX_LEVERAGE` являются жёсткими верхними границами для всех capital profiles; `risk_rate` также не может превышать профильный общий лимит. Небезопасный legacy-профиль блокирует plan/acceptance, а не расширяет риск.
- Некалиброванный baseline может формировать диагностический market signal, но по умолчанию не создаёт исполнимый план и не может быть принят оператором.
- Для ML artifacts TIMEOUT gross return оценивается отдельно для LONG/SHORT как медиана train-only TIMEOUT returns в единицах stop-risk и масштабируется к текущей barrier geometry. `TIMEOUT_GROSS_RETURN_RATE` остаётся явным fallback только для baseline/legacy diagnostic paths; опубликованный signal сохраняет фактически использованное значение, и plan/acceptance не пересчитывают его из текущего `.env`.
- Stateful features (EMA/ATR/rolling statistics) рассчитываются только внутри непрерывного сегмента валидных часовых свечей.
- Публикация hourly signal требует точной confirmed decision candle: последний `close_time` обязан совпадать с `event_time`; предыдущая свеча вызывает fail-closed `missing_decision_candle`, а не ранний сигнал текущего часа.
- Hourly market-close job сохраняет `symbols_total`/`symbols_covered` и повторно запрашивает отсутствующие exact last-price candles после cooldown, максимум пять раз; полный охват или исчерпание лимита завершает retry без ослабления inference gate.
- Для свечей `close_time` отражает рыночное закрытие, а `available_at` — фактическое время получения ответа. Поздний backfill не может появиться в point-in-time replay задним числом.
- Планирование использует свежий point-in-time orderbook: LONG потребляет asks, SHORT — bids; размер ограничивается меньшим из turnover cap и доступного depth внутри `MAX_VWAP_IMPACT_BPS`, а entry пересчитывается по complete-fill VWAP. Partial/no-fill блокируется. Перед `ACCEPTED` система повторяет depth/VWAP simulation, account/profile-scoped portfolio-risk, funding, reconciliation и instrument checks; несовместимый legacy-план или ухудшившееся исполнение создаёт новую версию.
- Каждая plan version в той же транзакции создаёт immutable selection-ledger row с eligibility status, фиксированным набором только ex-ante признаков и SHA-256. Outcomes и решения не записываются в feature snapshot.
- Локальный UI отдельно фиксирует first exposure plan version: ≥50% карточки должна быть видима не менее 1 секунды при `document.visibilityState=visible`. Selection report использует только exposed opportunities, публикует coverage и решения без exposure и блокирует IPSW при недостаточном instrumentation coverage.
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
python manage.py report         сформировать ежедневный отчёт, включая selection diagnostics
python manage.py selection-report  сформировать 90-дневный отчёт смещения отбора
python manage.py drift-report    сформировать отчёт production drift
python manage.py experiment-preregister  проверить/зарегистрировать experiment family
python manage.py experiment-report -- --family <name>  оценить preregistered disclosure, PBO и DSR
python manage.py release-check  проверить release tree и SHA256SUMS
```


## Формальная preregistration research family

Новые experiment families в 1.20.0 нельзя запускать без предварительной регистрации. Сначала сформируйте шаблон без model evaluation:

```bash
python manage.py backtest -- \
  --model models/candidate.joblib \
  --experiment-family momentum-policy-study-01 \
  --prepare-preregistration research/momentum-policy-study-01.json \
  --search-parameter minimum_net_rr \
  --search-parameter minimum_net_ev_r
```

Отредактируйте гипотезу, полный набор допустимых значений, stopping rule и exclusion criteria. Затем:

```bash
python manage.py experiment-preregister -- \
  --spec research/momentum-policy-study-01.json \
  --validate-only
python manage.py migrate
python manage.py experiment-preregister -- \
  --spec research/momentum-policy-study-01.json
```

После регистрации все backtests должны использовать точное имя family. Registration immutable; исправление ошибки выполняется новой family, а не редактированием строки. Pre-1.20 families остаются в ledger, но не объявляются preregistered.

## Конфигурация

`manage.py configure` создаёт локальный `.env`. Реальные credentials не должны попадать в архив или систему контроля версий. Шаблон переменных находится в `.env.example`.

`MODEL_ENTRY_SPREAD_BPS` задаёт полный bid/ask spread stress для historical labels. Значение делится пополам вокруг следующего hourly open: LONG моделируется по ask-side proxy, SHORT — по bid-side proxy. Изменение этой переменной меняет label geometry; после обновления требуется обучить новый artifact. Release 1.21.0 требует migration `0014_ui_exposure_ledger` и добавляет `SELECTION_MIN_EXPOSURE_COVERAGE=0.80`. Release 1.22.0 не добавляет migration или `.env`, но меняет model artifact contracts: после upgrade завершите instrument/funding history sync и переобучите candidate. Release 1.23.0 также не добавляет migration/`.env` и не меняет artifact contract; после обновления перезапустите worker и сформируйте новый drift report. Для непрерывного live-context refresh сохраняйте `UNIVERSE_SYNC_MARK_PRICE=true` и `UNIVERSE_ENRICH_FUNDING_OI=true`.

`EXPERIMENT_*` и `RESEARCH_*` задают defaults для нового preregistration template; зарегистрированная family использует только immutable значения specification. `SELECTION_DEPENDENCE_*` задают signal-cluster block geometry, а `SELECTION_MIN_EXPOSURE_COVERAGE` — минимальную долю instrumented eligible opportunities с подтверждённым UI exposure. Эти параметры не входят в live inference, не изменяют risk limits и не запускают auto-activation. Текущий migration head — `0014_ui_exposure_ledger`; переобучение active model не требуется.

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

Worker синхронизирует read-only market/account data, instrument specifications, confirmed candles, ticker/funding snapshots и point-in-time orderbook snapshots, а также прогрессивно backfill-ит last-price candles, hourly mark-price candles и фактические funding settlement events. Неполные или устаревшие данные блокируют публикацию либо исполнение. Для hourly decision последняя confirmed свеча должна закрываться точно в `event_time`; execution plan дополнительно требует свежий depth snapshot с биржевым и локальным временем получения.

Для point-in-time целостности время получения внешнего ответа фиксируется после завершения соответствующего API-вызова. Открытая свеча может обновляться до первого подтверждённого снимка; уже подтверждённая свеча считается неизменяемым рыночным фактом и не перезаписывается без отдельной аудируемой revision policy. Inference отдельно ограничивает рыночное время данных (`market cutoff`) и момент фактического решения (`availability cutoff`).

### Trainer

Trainer работает отдельно от API и inference worker. Он:

1. строит point-in-time dataset из confirmed hourly last-price candles, точной hourly mark-price timeline и historical funding settlements;
2. формирует direction-specific labels и отдельный realized-only intrahorizon margin path;
3. разделяет train/calibration/final holdout по времени и выполняет purged expanding walk-forward;
4. исключает пересечение label horizon с последующим окном;
5. обучает candidate artifact;
6. сравнивает candidate и incumbent только на совместимом holdout с одинаковыми horizon, label, funding, margin-path semantics, leverage и ATR barrier geometry;
7. активирует candidate только после absolute и relative gates.

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

## Operator-selection experiment ledger

При создании любой execution-plan version система сохраняет отдельную строку `advisory.selection_experiment_ledger`. Строка содержит eligibility status, planning timestamp, идентификаторы signal/profile/plan, фиксированную схему видимых до решения числовых признаков и SHA-256 canonical payload. Решение оператора и результат плана присоединяются только при построении отчёта; они не могут попасть в propensity features.

`python manage.py selection-report -- --days 90` создаёт `reports/operator_selection_bias.json`. Начиная с 1.21.0 denominator включает только eligible plan versions с verified first UI exposure; exposure time используется для chronological propensity ordering. Отчёт раскрывает created/exposed/unexposed counts, exposure coverage и решения без exposure. При coverage ниже `SELECTION_MIN_EXPOSURE_COVERAGE`, повреждении ledger, class collapse, слабом overlap/ESS или недостатке независимых signal clusters corrected estimate блокируется. UI event доказывает отображение карточки, но не направление взгляда, понимание рекомендации или отсутствие latent operator state.

`python manage.py drift-report` создаёт `reports/production_drift.json`. Reference берётся из final holdout активного artifact; calibration baseline использует тот же selected-direction cohort, что и production outcomes. Для calibration учитываются только сигналы с `event_time + horizon_hours <= report.generated_at`; ранние TP/SL незрелых сигналов исключаются, а любой unresolved mature signal даёт `incomplete_mature_outcome_coverage` и `BLOCKED`. Поле `outcome_coverage` раскрывает mature/resolved/unresolved counts и долю покрытия. PSI рассчитывается по фиксированным holdout-бинам. Failed inference jobs, недостаточная coverage/missingness или малая выборка также дают `BLOCKED`; `CRITICAL` и `BLOCKED` отображаются как `DEGRADED` в worker heartbeat. Поле `automatic_model_action` всегда равно `none`.


## Временная семантика ML

Часовой feature row становится доступен только после закрытия исходной свечи. Dataset хранит:

- `source_open_time` — начало исходной свечи;
- `decision_time` — её закрытие и момент доступности признаков;
- `label_end_time` — закрытие последней свечи label horizon.

Train/calibration/final holdout формируются по `decision_time`; labels предыдущего окна обязаны завершиться раньше следующего окна. Stateful features сбрасывают состояние на gap, duplicate или невалидной OHLCV-свече; label-window с нечисловой/некогерентной ценой исключается. Исполнимый proxy входа — direction-specific adverse half-spread вокруг `open` первой часовой свечи, начинающейся в `decision_time`; барьеры центрируются на этой цене и масштабируются сохранённым `atr_pct_14`. Новые artifacts используют `feature_schema_version=hourly-barrier-market-context-v5`, `market_context_schema=hourly-oi-basis-settled-funding-turnover-v2`, `historical_funding_schema=bybit-settlement-timestamp-replay-v2`, `funding_interval_schedule_schema=instrument-spec-point-in-time-v1`, `label_path_schema_version=decision-open-directional-spread-entry-ohlc-path-v3`, `temporal_split_schema=final-holdout-plus-expanding-walk-forward-v4` и `walk_forward_schema=expanding-train-rolling-calibration-purged-v1`. Runtime и promotion gate требуют point-in-time interval evidence; legacy artifacts нужно переобучить.

## Experiment-selection governance

Каждая backtest-оценка, дошедшая до валидированных artifact и final-test cohort, создаёт prospective trial в `research.experiment_events`. До расчёта записывается `STARTED` с canonical configuration hash; после расчёта — `SUCCEEDED` с выровненным почасовым return path либо `FAILED` с ограниченной диагностикой. События образуют SHA-256 hash chain и не заменяются mutable итоговой строкой. Повтор одной конфигурации учитывается как повторная попытка, но не как новый независимый вариант.

Каждый executable backtest обязан использовать точное имя заранее зарегистрированной `experiment_family`; автоматическое создание family из результата отключено. Все сравниваемые конфигурации должны иметь один и тот же timestamp grid. Затем выполните:

```bash
python manage.py experiment-report -- --family <exact-family-name>
```

Отчёт применяет contiguous combinatorially symmetric cross-validation для PBO, выбирает конфигурацию по non-annualized Sharpe и рассчитывает Deflated Sharpe probability с учётом skewness, kurtosis, числа зависимых trials и Newey–West effective observation count. Выбранный return path дополнительно получает Bartlett-HAC mean interval и moving-block intervals для mean/Sharpe; effective block length не может быть короче horizon. `READY` требует не только PBO/DSR thresholds, но и положительные нижние dependence-aware bounds. `STARTED` без terminal event, unresolved `FAILED`, недостаток blocks/trials/periods, несовпадающие timestamps или повреждённая hash chain дают `BLOCKED_*`. `automatic_model_action=none` и `profitability_claimed=false` обязательны.

Evidence trial ledger накапливается только после migration 1.18.0, formal family preregistration — после 1.20.0, а verified UI exposure — после 1.21.0. Старые backtests и pre-1.20 families не backfill-ятся как preregistered evidence; pre-1.21 unexposed plans не считаются пропущенными exposures. Propensity bootstrap остаётся условным на уже fitted OOS scores, external trusted timestamp отсутствует, а experiment report не является promotion gate active model.

## Research backtest

Backtest загружает artifact через тот же runtime validator, что и production; при необходимости `--model-sha256` фиксирует ожидаемый hash. Research dataset атомарно создает ровно одну LONG- и одну SHORT-строку на symbol/timestamp и сохраняет `entry_price` для аудита; если геометрия хотя бы одного направления невалидна, исключается весь cohort. До выбора направления все строки проверяются на допустимый target, finite barrier/return, exit index и доступность label; поврежденная проигравшая строка не может исчезнуть из проверки. Temporal split, holdout policy и backtest повторно проверяют этот контракт fail-closed. После проверки backtest выбирает не более одного направления по тому же порядку policy, что и production: максимальный net `EV/R`, затем net RR и детерминированный LONG tie-break. Runtime, holdout policy, backtest и Decimal risk math отвергают probabilities вне диапазона `[0, 1]`, с неединичной суммой либо нечисловыми значениями. Комиссия каждой ноги считается от фактического входного/выходного notional; slippage, stop-gap reserve, статический funding-сценарий и policy-пороги задаются отдельно. Исторический research replay учитывает только settlement events в окне `(entry_time, actual_exit_time]`; положительный exchange funding означает расход LONG и доход SHORT. Будущая фактическая ставка не используется для ex-ante выбора направления. CLI `--funding-rate` остаётся отдельным неблагоприятным stress-сценарием для ожидаемой экономики и не переписывает realized historical cash flow.

Для горизонта `H` часов капитал делится на `H` равных sleeves. Часовой cohort использует один sleeve и этот капитал не переиспользуется до завершения максимального label horizon. Средние promotion-метрики рассчитываются сначала внутри каждого hourly cohort; количество символов в одном часу не создает дополнительные независимые наблюдения. Для uncertainty gate все timestamps разбиваются на `H` epoch-hour phases, каждая из которых содержит неперекрывающиеся label windows. Фазы балансируются до одинаковой недавней длины, а gate использует минимальные phase mean и phase LCB, поэтому результат не зависит от первого timestamp holdout. Auto-activation требует минимум как raw trades, так и независимых `policy_cohorts`, а также `policy_trade_rate >= AUTO_TRAIN_MIN_POLICY_TRADE_RATE` (default 1%). Доля пересчитывается как `policy_trades / policy_candidates` и проверяется на внутреннюю согласованность; malformed или статистически микроскопическая policy блокируется fail-closed. Gross gain и gross loss для profit factor суммируются по отдельным trade contributions до агрегации по времени выхода; одновременные прибыль и убыток не взаимопогашаются. Положительный holdout без отрицательных trade contributions представляет profit factor как математически неограниченный только при явных `gross_gain > 0` и `gross_loss = 0`; отсутствие сделок или неполные метрики остаются fail-closed. Дополнительно research-поток применяет live-инвариант «не более одного активного плана на symbol в одном account scope»: следующий кандидат того же символа исключается до modeled exit предыдущего, а вход ровно на границе выхода разрешён. Число исключённых кандидатов публикуется как `overlap_blocked_trades` / `policy_overlap_blocked_trades`. Поэтому перекрывающиеся H-часовые returns не компаундятся как последовательные одночасовые сделки, не создают скрытое H-кратное плечо и не завышают promotion evidence сделками, которые live acceptance отклонил бы. PnL зачисляется в equity curve в modeled candle exit time. Метрики concurrency считают реально открытые позиции, а не только новые входы в один timestamp.

`net_return` отражает наблюдаемый gross outcome за вычетом фактических модельных fee/slippage/funding и не списывает неиспользованный stop-gap reserve как денежный убыток. Любой состоявшийся gap уже находится в `realized_gross_return`. Консервативный остаточный reserve остаётся в downside для sizing/actionability и отдельно публикуется как `stress_net_return_with_stop_gap_reserve`; legacy-поле `net_return_without_stop_gap_reserve` сохранено как совместимый alias фактического `net_return`.

Research backtest моделирует realized-only intrahorizon mark-to-market по точной hourly Bybit mark-price OHLC timeline, учитывает фактически пересечённые funding settlements и консервативно ставит liquidation touch раньше более позднего неупорядоченного last-price TP/SL touch в том же bar. Для каждого decision/settlement используется funding interval из point-in-time `InstrumentSpecHistory`; стабильные участки проверяются точно, а переходы interval — консервативно по наблюдаемой event cadence. Симулятор остаётся isolated-margin research proxy: он не реконструирует sub-hour mark path, исторические maintenance-margin/risk-tier изменения, liquidation fees, cross/portfolio margin, ADL, страховой фонд или точный fill. Полный historical order book, queue position и historical fill/latency trajectory до 1.14.0 отсутствуют. Prospective depth/VWAP/FULL-PARTIAL-NO_FILL и operator-latency evidence накапливается только с 1.14.0; historical funding forecast snapshots и интервалы до первой локально наблюдаемой spec-записи по-прежнему не реконструируются.
Эти ограничения означают, что прохождение unit tests или promotion gate не подтверждает live-edge: historical entry остаётся next-hour open proxy, а live plan использует более поздний executable bid/ask и ручное решение оператора. Release 1.14.0 начал накапливать point-in-time liquidity snapshots и operator-latency evidence; release 1.15.0 добавил prospective selection ledger; release 1.22.0 устранил применение последнего funding interval ко всей наблюдаемой истории; release 1.23.0 устранил right-censoring calibration drift незрелыми early-exit outcomes. До появления достаточной forward-истории, historical funding-forecast snapshots, подтверждённых pre-observation interval records и более детальной queue/fill траектории разрыв должен считаться существенным модельным риском.

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
- Historical labels до накопления prospective evidence используют spread/entry proxy, а не архивные bid/ask и depth. Live plan моделирует bounded-depth VWAP и блокирует PARTIAL/NO_FILL, но queue position, exact exchange fill probability и pre-1.14 history отсутствуют.
- Research validation использует трёхфолдовый purged expanding walk-forward внутри development period и отдельный final holdout. Prospective trial ledger, formal family preregistration, contiguous CSCV/PBO, HAC-adjusted DSR, dependence-aware intervals и production drift monitoring реализованы как governance/diagnostic layers; nested hyperparameter selection, conditional search-space schemas, studentized bootstrap и automatic promotion по этим отчётам отсутствуют.
- Intrahorizon mark-to-market реализован как conservative hourly mark-price isolated-margin proxy; exact sub-hour path, historical MMR/risk tiers, cross/portfolio margin и liquidation fees отсутствуют.
- Техническая корректность расчётов и тестов не означает наличия статистически устойчивого торгового преимущества.
