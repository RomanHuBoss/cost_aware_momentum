# Cost-aware hourly ML momentum

> Версия 1.52.1: недостаток post-filter истории для purged walk-forward больше не переводит background trainer в аварийный `ERROR`: задача завершается fail-closed как диагностируемый `DEFERRED`, сохраняет exact capacity и ждёт новых данных. Decision-time execution contract теперь выводит безопасные структурированные причины и сравниваемые параметры в JSON-логах.

Локальная advisory-only система для анализа linear USDT perpetuals Bybit. Она получает рыночные данные, строит часовые признаки, оценивает сценарии LONG/SHORT, учитывает комиссии, проскальзывание, funding, риск и портфельные ограничения и показывает оператору исполнимый план. Приложение не размещает, не изменяет и не отменяет биржевые ордера.

## Основные свойства

- FastAPI API и локальный веб-интерфейс.
- PostgreSQL как единственная база данных.
- Отдельные процессы API, inference worker и trainer.
- Read-only интеграция с Bybit.
- Direction-conditional модель исходов `TP / SL / TIMEOUT`; `NO TRADE` остаётся решением policy layer.
- Artifact model использует 10 OHLCV-derived и 7 point-in-time market-context features: OI momentum, mark/index basis, settled funding state и turnover/OI liquidity proxy. Точный OI/basis и свежий funding anchor обязательны; zero-fill и future event leakage запрещены.
- Runtime возвращает оба directional-сценария; окончательный LONG/SHORT выбирается market-signal policy по текущим bid/ask, комиссиям, slippage и barrier geometry. Пока historical point-in-time funding forecasts отсутствуют, ex-ante funding в этой promotion-bound policy равен нулю. Свежий projected funding применяется execution-plan/acceptance layer как консервативный блокирующий overlay и не может развернуть уже валидированное направление.
- Immutable model artifacts, SHA-256, candidate/incumbent comparison и guarded activation. Начиная с 1.36.0 exact bytes каждого нового candidate атомарно архивируются в PostgreSQL в той же транзакции, что и registry/audit; worker, trainer и activation service проверяют архив и восстанавливают release-local файл до загрузки runtime. Для перехода 1.50→1.51 legacy estimator допускается только к отдельной benchmark-загрузке с проверкой exact SHA/version/core schemas и пересчётом на новом tick-aligned holdout; production `ModelRuntime` его по-прежнему отклоняет.
- Staged background promotion: quality-passed inactive candidate повторно проверяется после завершения preregistered backtests и может быть активирован без повторного обучения; exact artifact binding, active-version concurrency и audit/outbox остаются обязательными.
- Все normal state-changing activation paths fail-closed требуют два независимых контракта: непротиворечивый passed model quality gate и passed `model-promotion-experiment-governance-v3`, связанный с exact version/SHA-256/horizon и тем же deployment-policy contract, который будет использовать production. Изменение live executable spread, fees/slippage/stop-gap/EV-RR thresholds после backtest инвалидирует promotion evidence. Ручной emergency rollback требует одновременно `--emergency-gate-override` и непустой `--override-reason`; исходная evidence и override сохраняются в `MODEL_ACTIVATED` audit payload.
- Production drift monitoring сравнивает только активную model version с её immutable final-holdout reference: feature/probability PSI, terminal processing coverage, maturity-corrected selected-direction calibration и actionability density. Начиная с 1.49.0 coverage считается по exact `symbol_outcome_count / symbols_total`, а recommendation density — по `(published + existing_current_hour) / symbols_total`; легитимные `SKIPPED`/`NO TRADE` outcomes являются завершённой обработкой, а не потерей coverage. Reference actionability связан с final post-overlap `policy_trades / policy_candidates` через `published-policy-trades-per-symbol-opportunity-v1`. Ранние barrier outcomes до полного horizon не входят в calibration; unresolved mature outcomes блокируют только calibration evidence. Report v4 раздельно сохраняет `critical_evidence`, `blocking_evidence` и `warning_evidence`: independently confirmed critical feature/probability/actionability drift или валидная calibration drift имеет приоритет над одновременной неполнотой другой части evidence и ставит exact active version на fail-closed quarantine. Calibration-only alert удаляется из critical evidence, если maturity coverage неполно или невалидно. Pure warm-up/incomplete evidence остаётся `BLOCKED`, не останавливает prospective bootstrap и только деградирует heartbeat. Drift выполняется до inference; quarantine блокирует новые signals, переводит plans в `NO_TRADE`, запрещает acceptance старого actionable plan, переживает restart/disable monitor и снимается только другой model version.
- Candidate/live attrition diagnostics prospectively фиксируют ровно один terminal outcome для каждого `symbol × event_time`, точную причину каждого initial execution plan и quality-gate/activation outcome каждого background training attempt. Report v3 дополнительно связывает instrumented signals/plans с exact persisted outcomes: TP/SL/TIMEOUT и valued-plan `counterfactual_r` агрегируются по initial status, terminal stage и primary reason только после полного horizon. Ранние barrier outcomes и outcomes с `resolved_at` после `report.until` исключаются, а missing/conflicting mature evidence блокирует attribution. Это descriptive counterfactual diagnostic, не actual execution PnL и не causal estimate.
- Research experiment-selection governance prospectively учитывает все backtest-конфигурации одной family, включая failed/open attempts; по выровненным почасовым return paths считает CSCV/PBO, HAC-adjusted Deflated Sharpe и moving-block confidence intervals. Nominal и обязательные cost-stress пути ×1,5/×2 содержат genuine no-trade/holding hours внутри наблюдавшихся decision-to-horizon окон, исключают недоступные календарные разрывы и отражают cumulative hourly mark-close MTM: entry fee и conservative slippage признаются в decision time, historical funding — по settlement path, terminal exit fee и barrier/liquidation outcome — в effective exit. Неполный/legacy ledger, недостаток независимых временных блоков или отрицательный terminal capital return выбранной конфигурации в любом cost-stress сценарии блокирует normal promotion. Activation принимает только report `experiment-selection-preregistered-governance-v4` со статусом `READY`, exact artifact/deployment-policy binding и persisted cost-stress evidence.
- Formal experiment-family preregistration фиксирует гипотезу, точный cohort fingerprint/horizon, полный search space, primary metric, thresholds, stopping budget/deadline и допустимые exclusion criteria до первого `STARTED`. Trial вне контракта не вычисляется.
- Promotion gate отдельно проверяет raw trades, неперекрывающиеся по label horizon временные когорты и минимум 168 часов final holdout; число символов не заменяет временную глубину. До final holdout candidate обязан пройти три последовательных purged expanding walk-forward folds с независимым переобучением и калибровкой.
- Экономический promotion gate использует не только point mean R, но и 95% one-sided lower confidence bound. Для горизонта `H` часов отдельно оцениваются все `H` неперекрывающихся часовых фаз; gate использует худшую фазовую LCB и требует полного покрытия фаз. Default требует `LCB > 0`.
- Exact actionable final holdout отдельно проверяется по направлениям LONG и SHORT на полной наблюдаемой opportunity-сетке. Каждое фактически торгуемое направление должно иметь не менее пяти сделок, положительный opportunity-weighted mean R и calibration в существующих log-loss/Brier пределах; прибыльная сторона не может маскировать убыточную.
- Final-holdout policy дополнительно проходит per-symbol jackknife: для каждого реально торгуемого symbol весь его actionable cohort удаляется, оставшиеся одновременные сделки перевзвешиваются, а отсутствующие сделки остаются нулевыми opportunity hours. Кандидат блокируется, если без любого одного symbol результат не остаётся выше `AUTO_TRAIN_MIN_POLICY_REALIZED_MEAN_R`; single-symbol edge не auto-активируется.
- Поверх symbol jackknife строятся детерминированные компоненты зависимости: symbols соединяются при `|Pearson correlation| >= 0.70` минимум на восьми совместно торгуемых timestamps. Кандидат блокируется, если после удаления любого целого компонента результат exact opportunity cohort не остаётся выше того же minimum policy mean R.
- До запуска bootstrap trainer вычисляет необходимую часовую историю из feature warm-up, horizon, temporal split и holdout gates. При defaults требуется не менее 1206 уникальных часовых timestamps; это необходимое, но не достаточное условие при гэпах/невалидных свечах. На чистой dynamic-установке trainer фиксирует последний hash-validated execution-eligible universe snapshot, использует его как неизменяемый cohort для historical candle bootstrap и явно маркирует artifact `historical_frozen_dynamic_bootstrap`. Историческая membership не выдумывается: exact prospective snapshots продолжают копиться отдельно, а после достаточного span trainer автоматически переходит на `prospective_dynamic_replay`.
- `AUTO_TRAIN_MAX_SYMBOLS` ограничивает только frozen historical bootstrap после текущего dynamic ranking; exact prospective replay намеренно не делает full-sample preselection по candle coverage, чтобы не вносить survivorship/selection look-ahead. Background trainer переносит exact symbols и cutoff из preflight profile в fit, сверяет их с hash-bound snapshot evidence и после feature/context/label filtering повторно проверяет symbol scope, верхнюю границу времени и `AUTO_TRAIN_MIN_SYMBOL_COVERAGE_RATIO`.
- Каждый universe refresh, прошедший market-sync transaction, сохраняет `market.universe_eligibility_snapshots`: полный point-in-time decision set по всем instrument rows, точный policy hash, selected rank/reason и наблюдавшиеся turnover/spread/age/status. UPDATE/DELETE запрещены PostgreSQL trigger; in-memory universe меняется только после commit. Для dynamic research replay широкая membership (`UNIVERSE_MAX_SPREAD_BPS`) дополнительно пересекается с exact live executable cohort (`MAX_SPREAD_BPS`) по сохранённому bid/ask spread; pre-ledger membership по-прежнему не реконструируется.
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
- Hourly inference завершает processing scope по `symbol_outcome_count`: каждый selected symbol обязан иметь один terminal outcome `PUBLISHED`, `EXISTING_CURRENT_HOUR` или `SKIPPED`. Редкие рекомендации не вызывают повторный inference; retry выполняется только при фактически отсутствующем terminal outcome. Production drift использует тот же terminal count для coverage и отдельно считает signal density.
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
python manage.py report         сформировать ежедневный отчёт, включая selection, drift и attrition diagnostics
python manage.py selection-report  сформировать 90-дневный отчёт смещения отбора
python manage.py drift-report    сформировать отчёт production drift
python manage.py attrition-report -- --hours 168  сформировать candidate/live attrition report
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


## Безопасная активация модели

Обычная ручная активация допускается только для зарегистрированной версии с сохранённым passed quality gate:

```bash
python manage.py model-registry activate --version <version> --experiment-family <family>
```

`python manage.py train --activate ... --experiment-family <family>` вычисляет оба gate. Fresh artifact обычно ещё не имеет полного preregistered family report, поэтому регистрируется неактивным. Начиная с 1.32.0 background trainer при пустом `AUTO_TRAIN_EXPERIMENT_FAMILY` и `AUTO_TRAIN_AUTO_EXPERIMENT=true` сам формирует candidate-specific family, заранее регистрирует неизменяемую гипотезу, полный фиксированный RR/EV grid и stopping rule, а затем последовательно запускает formal backtests. Grid обязательно содержит точную deployment policy; наблюдавшиеся результаты не могут расширить или изменить search space. Candidate активируется только после существующих quality, PBO/DSR, dependence, cost-stress, exact artifact/horizon и exact deployment-policy gates. Явный `AUTO_TRAIN_EXPERIMENT_FAMILY=<family>` по-прежнему имеет приоритет и предназначен для operator-reviewed family. `AUTO_TRAIN_AUTO_EXPERIMENT=false` сохраняет прежний режим ожидания. Ручная команда `model-registry activate` остаётся review/rollback-инструментом.

Release 1.36.0 добавляет таблицу `model.model_artifact_blobs`. При регистрации candidate exact bytes, SHA-256 и размер записываются в одной PostgreSQL transaction с `ModelRegistry`, audit и outbox. Файл в `MODEL_DIR` остаётся runtime-копией, а не единственным источником истины. Если путь из registry исчез после замены каталога release, worker/trainer/activation service сначала проверяют неизменяемую копию в PostgreSQL, атомарно материализуют новый файл и обновляют `artifact_path`. Повреждённый DB payload, несовпадение hash/version/size или artifact больше 256 MiB блокируют operation. Уже утраченный pre-1.36.0 файл не может быть восстановлен из ничего: если старый файл ещё доступен, первый worker/trainer/activation check архивирует его; если его нет, требуется governed recovery training.

Начиная с 1.33.0 окно «Обучатель моделей» и `/api/v1/status` показывают exact candidate/family, этап, номер конфигурации, attempt и факт активного subprocess. Аутентифицированный оператор может остановить только текущую exact family/candidate через `CANCEL_EXPERIMENT`. Trainer проверяет target по свежему heartbeat, принимает запрос из PostgreSQL во время ожидания child process, сначала посылает terminate, затем при необходимости bounded kill. Уже зарегистрированная preregistration и все предыдущие experiment events остаются неизменными; open `STARTED` получает append-only `FAILED`, activation request exact candidate закрывается, active incumbent не затрагивается. Stale или mismatched cancel request не может остановить другую family.
Начиная с 1.34.0 formal backtest запускается в изолированном process tree. На POSIX используется новая session/process group и сигналы направляются всей группе (`SIGTERM`, затем `SIGKILL`); на Windows subprocess получает `CREATE_NEW_PROCESS_GROUP`, а остановка использует встроенный `taskkill /T` с `/F` fallback. Cancel, timeout, non-zero exit и ошибка control probe используют один fail-closed cleanup path. Terminal evidence сохраняет schema, scope, root PID, способ завершения и признак проверки дерева; unsupported OS не запускает незащищённый subprocess. Намеренно отделившийся POSIX descendant, создавший собственную session через `setsid()`, не входит в process-group гарантию.

Аварийный rollback к legacy/старой версии без passed gate требует двух явных аргументов:

```bash
python manage.py model-registry activate --version <version> \
  --emergency-gate-override \
  --override-reason "Rollback after documented incumbent integrity incident"
```

Override не является способом обойти плохие метрики ради большего числа рекомендаций. Причина и исходный gate попадают в append-only audit payload.

## Конфигурация

`manage.py configure` создаёт локальный `.env`. Реальные credentials не должны попадать в архив или систему контроля версий. Шаблон переменных находится в `.env.example`.

`MODEL_ENTRY_SPREAD_BPS` задаёт полный bid/ask spread stress для historical labels. Значение делится пополам вокруг следующего hourly open: LONG моделируется по ask-side proxy, SHORT — по bid-side proxy. `ENTRY_ZONE_ATR_FRACTION` задаёт неизменяемую зону вокруг close decision candle; stressed next-hour open в research и текущие bid/ask в live обязаны находиться внутри неё. `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS` ограничивает задержку публикации после event time и не может быть меньше `INFERENCE_DELAY_SECONDS` либо достигать TTL. Изменение этих параметров меняет deployment-policy/artifact contract и требует нового candidate. Release 1.21.0 требует migration `0014_ui_exposure_ledger` и добавляет `SELECTION_MIN_EXPOSURE_COVERAGE=0.80`. Release 1.22.0 не добавляет migration или `.env`, но меняет model artifact contracts: после upgrade завершите instrument/funding history sync и переобучите candidate. Release 1.23.0 также не добавляет migration/`.env` и не меняет artifact contract; после обновления перезапустите worker и сформируйте новый drift report. Release 1.24.0 не меняет schema/artifact/config: перезапустите worker и trainer, чтобы новые `JobRun.details` начали накапливать terminal attrition evidence. Release 1.25.0 не меняет DB/artifact/config, но ужесточает activation contract: обычная активация требует persisted passed gate, а emergency rollback без него требует явной причины. Release 1.26.2 не требует migration или переобучения, но документирует `AUTO_TRAIN_EXPERIMENT_FAMILY`: после регистрации нового quality-passed background candidate укажите family, preregistered под его exact version/SHA-256/horizon, и перезапустите trainer. Пустое значение оставляет candidate inactive. Release 1.26.3 не добавляет migration или `.env`, но повышает normal-promotion contract до v2: pre-1.26.3 inactive candidates не имеют immutable policy binding и должны быть переобучены перед обычной активацией; уже active artifact продолжает работать, а reviewed emergency rollback остаётся доступным. Release 1.26.4 также не добавляет migration/`.env`, но меняет policy metric schemas на opportunity-path v17/v3: уже active artifact продолжает inference, а inactive candidate с прежними quality metrics должен быть переобучен и заново пройти governed experiment family перед normal activation. Release 1.29.0 требует migration `0015_universe_eligibility`; после upgrade перезапустите worker, чтобы начать prospective накопление exact universe-eligibility evidence. Release 1.31.0 требует migration `0016_universe_replay_asof`; она добавляет индекс PostgreSQL для latest-prior replay и не меняет накопленные snapshots. Перед запуском trainer/backtest выполните `python manage.py migrate`. Release 1.32.0 не добавляет migration, но добавляет автоматический bounded experiment lifecycle и новые `AUTO_TRAIN_EXPERIMENT_*` настройки. Release 1.33.0 также не требует migration или новых `.env`: он добавляет exact-target status/cancel control в существующий authenticated trainer API/UI. Release 1.34.0 не меняет migration/config/API и добавляет process-tree containment для automatic experiment subprocess; после обновления перезапустите trainer (API можно перезапустить вместе с ним). Release 1.34.1 также не требует migration, `.env` или переобучения active artifact: после обновления перезапустите inference worker/API. Market signal использует promotion-bound `policy_expected_funding_source=none-no-point-in-time-forecast`, а каждый execution plan и acceptance продолжают независимо пересчитывать свежий projected funding. Для непрерывного live-context refresh сохраняйте `UNIVERSE_SYNC_MARK_PRICE=true` и `UNIVERSE_ENRICH_FUNDING_OI=true`. Release 1.34.2 не добавляет migration, `.env` или model-artifact changes. После обновления перезапустите trainer; существующие universe snapshots не переписываются. Если хеш действительно повреждён, fail-closed ошибка теперь указывает `snapshot id`, `mode` и `recorded_at` для диагностики. Release 1.35.0 также не требует migration, `.env` или переобучения: перезапустите API/worker, затем дождитесь завершения counterfactual outcome job и заново сформируйте attrition report. Защитные model/policy/risk gates не изменены. Release 1.35.1 не требует migration, `.env` или переобучения active artifact: перезапустите API/worker. Для conditional artifacts execution plan и acceptance теперь пересчитывают TIMEOUT gross return из immutable `timeout_return_r` по текущему executable entry/VWAP; legacy signals без `R` остаются обратно совместимыми. Release 1.35.2 также не требует migration, `.env` или переобучения: перезапустите API/worker. Ticker lookup теперь выбирает последнюю запись, уже доступную к точному decision/request cutoff; будущая запись не блокирует использование предыдущей свежей котировки. Release 1.35.3 не требует migration, `.env` или изменения model artifact schema: перезапустите trainer и API. Legacy pending candidate без current policy binding либо с утраченным/повреждённым artifact будет terminally закрыт с audit/outbox evidence; scheduler затем покажет фактическую data/quality/recovery причину вместо вечного `candidate_policy_binding_missing_or_invalid`. Production inference остаётся fail-closed при утрате active artifact, но operator/background recovery training доступен. Release 1.35.4 не требует migration, `.env` или переобучения active artifact: перезапустите API/worker. Endpoint exposure теперь классифицирует каждый item независимо и не возвращает batch-wide 409 из-за stale/legacy card; browser повторяет только transport/5xx/429 failures с тем же `client_event_id`. Plan construction, acceptance, reconciliation и portfolio views используют latest-prior orderbook/account snapshots. Model quality, activation, EV/RR и risk gates не ослаблены. Release 1.35.5 также не требует migration, `.env` или переобучения: перезапустите inference worker. Каждый фактический hourly/catch-up inference attempt выполняет fail-closed ticker refresh в той же транзакции до signal publication; market poll получает отдельный финальный ticker response после долгих snapshot/backfill операций. `MAX_TICKER_AGE_SECONDS` не увеличен. Release 1.36.0 требует migration `0017_model_artifact_blobs`: остановите API/worker/trainer, выполните `python manage.py migrate`, затем перезапустите все три процесса. Новые candidates архивируются автоматически; существующий artifact архивируется при первом успешном durability check. Migration не создаёт байты для уже отсутствующего файла и не меняет `.env`, feature/label schema, quality/promotion thresholds или risk limits.




Release 1.52.0 не добавляет migration или API-breaking changes, но добавляет три `.env`-параметра с безопасными defaults: `AUTO_TRAIN_DYNAMIC_BOOTSTRAP_ENABLED=true`, `AUTO_TRAIN_BOOTSTRAP_MIN_SYMBOLS=3`, `AUTO_TRAIN_BOOTSTRAP_INSTRUMENT_SPEC_EXTRA_TICKS=1`. После обновления перезапустите worker и trainer. На чистой dynamic-базе первый candidate может обучаться на historical candles hash-bound frozen cohort сразу после загрузки не менее 1206 label-eligible часов и прохождения неизменённых quality/policy/experiment gates. Использование earliest locally observed tick для pre-observation history сопровождается adverse extra-tick stress и явным artifact evidence; точная historical universe membership, bid/ask и depth не реконструируются.

Release 1.51.1 не добавляет migration, API contract или `.env` variables. Перед распространением архива выполните `python manage.py release-check --write`, затем повторите `python manage.py release-check`: проверка требует полный release contract, согласованную версию и SHA-256 каждого допустимого файла.

Release 1.51.0 не добавляет migration или `.env` variables. После обновления перезапустите trainer/backtest/runtime и обучите новый candidate: label-path schema повышена до `decision-open-directional-spread-tick-aligned-entry-ohlc-path-v4`, entry-execution schema — до `decision-close-tick-zone-next-hour-open-directional-half-spread-v3`, policy metrics — до v26. Pre-1.51 artifacts отклоняются fail-closed production runtime. Для единственного перехода 1.50→1.51 trainer может SHA/version/core-contract-validated загрузить только estimator предыдущего incumbent и заново вычислить его metrics на текущем tick-aligned holdout; старые stored metrics и old runtime contract не переиспользуются. Решение использует только instrument specs с `valid_from <= decision_time` и `received_at <= decision_time`; свечи до первой реально сохранённой спецификации не получают выдуманный historical tick и могут быть исключены из research cohort. Ни один EV/RR, calibration, holdout, walk-forward, spread или risk threshold не снижен.

Release 1.50.0 добавляет обязательную migration `0018_inference_observations` и не меняет `.env`. Перед запуском API/worker/trainer выполните `python manage.py migrate`. Новый immutable ledger начинает накапливаться prospectively: исторические no-trade/model-evaluable observations до обновления не реконструируются. Existing active artifact переобучать не требуется; drift monitor будет `BLOCKED` по minimum observations во время warm-up, но это само по себе не включает quarantine. EV/RR, spread, calibration, promotion и risk thresholds не изменены.

Release 1.49.1 не добавляет новый Alembic head и не меняет `.env`. Исправлены уже выпущенные ревизии `0006_manual_trade_remaining_risk`, `0007_position_account_scope` и `0017_model_artifact_blobs`, потому что `0001_initial` на чистой базе создаёт текущую ORM-схему. После ошибки `DuplicateColumn` не удаляйте столбцы и не выполняйте `alembic stamp`: установите 1.49.1 и повторите `python manage.py migrate`. PostgreSQL transactional DDL оставляет Alembic на последней успешно завершённой ревизии; guards/backfill/constraint recreation продолжат цепочку без потери данных.

Release 1.49.0 не добавляет migration или `.env` variables, но повышает production-drift reference/report schemas до v4. Inference retry и drift coverage теперь используют exact terminal `symbol_outcome_count`; actionability density считается по published/existing signals относительно всех expected symbol opportunities, а reference rate — по final post-overlap policy trades. Перезапустите worker/API/trainer и обучите новый candidate: pre-1.49 artifacts содержат reference v3 и отклоняются fail-closed. Model quality, EV/RR, spread, holdout, walk-forward и risk thresholds не изменены.
Release 1.48.0 не добавляет migration или `.env` variables, но повышает policy metric schema до `decision-close-zone-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v25` и interaction schema до `symbol-direction-regime-supported-cells-sparse-pool-jackknife-v2`. Малые ячейки по-прежнему объединяются в один preregistered sparse-pool, но теперь для каждой из них рассчитывается `leave-one-sparse-interaction-cell-out-v1`: остаточный cohort должен иметь минимум пять сделок и пройти неизменённые economics/calibration limits. Перезапустите trainer/runtime и обучите новый candidate: pre-1.48 artifacts отклоняются fail-closed. Ни один EV/RR, calibration, holdout, walk-forward, spread или risk threshold не снижен.

Release 1.46.0 не добавляет migration или `.env` variables, но повышает policy metric schema до `decision-close-zone-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v23` и делает обязательным `actionable-policy-direction-opportunity-cohort-v1` поверх actionable calibration, regime, symbol и correlation-cluster checks. Перезапустите trainer/runtime и обучите новый candidate: pre-1.46 artifacts отклоняются fail-closed, поскольку не содержат отдельного LONG/SHORT economics/calibration evidence. Действующие EV/RR, calibration, holdout, walk-forward, spread и risk thresholds не снижены.

Release 1.42.0 не добавляет migration или `.env` variables, но повышает policy metric schema до `decision-close-zone-directional-spread-entry-funding-mark-mtm-liquidation-cohort-v19` и вводит обязательную `actionable-policy-trades-final-holdout-v1` calibration. Перезапустите trainer/runtime и обучите новый candidate: pre-1.42 artifacts намеренно отклоняются, поскольку не доказывают качество вероятностей на фактически торгуемом поднаборе. Все прежние ML, walk-forward, policy, EV/RR, spread и risk thresholds сохранены.

Release 1.41.0 не добавляет migration или `.env` variables, но повышает production-drift reference schema до `final-holdout-feature-probability-selected-calibration-reference-v3` и selected calibration cohort до `selected-direction-final-holdout-v2`. Перезапустите trainer/runtime и обучите новый candidate: pre-1.41 artifacts намеренно отклоняются как не содержащие доказуемый explicit selected-direction calibration contract. Все прежние ML, walk-forward, policy, EV/RR и risk thresholds сохранены.

Release 1.40.0 не добавляет migration, но добавляет `.env` variables `ENTRY_ZONE_ATR_FRACTION=0.12` и `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS=600`, повышает entry-execution schema до `decision-close-zone-next-hour-open-directional-half-spread-v2`, policy metrics до v18 и promotion-policy binding до v4. После обновления перезапустите worker и trainer и обучите новый candidate; pre-1.40 artifacts намеренно отклоняются runtime validator как несовместимые с decision-time entry contract; active artifact/config mismatch по zone/delay также блокирует publication fail-closed.

Release 1.39.0 не добавляет migration, `.env` или model-artifact contract. После обновления перезапустите inference worker. Перед каждым hourly/catch-up publish worker в одной транзакции обновляет read-only account state (если включён), order books и затем ticker batch; полный отказ orderbook refresh или private account refresh блокирует публикацию до записи новых signals. `MAX_ORDERBOOK_AGE_SECONDS`, `MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS`, `MAX_TICKER_AGE_SECONDS`, model gates и risk limits не расширены.

Release 1.38.0 не добавляет migration или `.env` variables. После обновления перезапустите trainer. Pending background attempt, созданный старой версией без exact preflight scope evidence, следует завершить/перезапустить; active artifact и inference не меняются. Новый candidate использует только symbols из trigger `training_data_profile` и raw candle upper bound `profile.end_time + horizon`.

Release 1.37.0 не добавляет migration или `.env` variables, но повышает universe replay до v2 и deployment-policy binding до v3. После обновления перезапустите trainer и backtest processes. Уже active artifact продолжает inference; inactive candidate или preregistered evidence с binding v2 не должны normal-activate и требуют нового candidate/backtest под текущим `MAX_SPREAD_BPS`. Существующие universe snapshots пригодны: точный spread уже хранится внутри immutable decisions. `UNIVERSE_MAX_SPREAD_BPS` остаётся широким discovery/observation лимитом, а `MAX_SPREAD_BPS` — точным live и research execution gate.

`EXPERIMENT_*` и `RESEARCH_*` задают defaults для нового preregistration template; зарегистрированная family использует только immutable значения specification. `AUTO_TRAIN_EXPERIMENT_RR_MULTIPLIERS` и `AUTO_TRAIN_EXPERIMENT_EV_ADDITIONS` задают неадаптивный grid относительно текущих `MIN_NET_RR`/`MIN_NET_EV_R`; он обязан включать multipliers/additions `1.0` и `0.0`, содержать не меньше `EXPERIMENT_MIN_TRIALS` и не больше 16 конфигураций. `AUTO_TRAIN_EXPERIMENT_TIMEOUT_SECONDS` ограничивает один subprocess, а `AUTO_TRAIN_EXPERIMENT_MAX_ATTEMPTS_PER_CONFIGURATION` — число записываемых попыток (1–3). `SELECTION_DEPENDENCE_*` задают signal-cluster block geometry, а `SELECTION_MIN_EXPOSURE_COVERAGE` — минимальную долю instrumented eligible opportunities с подтверждённым UI exposure. Эти параметры не входят в live inference и не изменяют risk limits; автоматический experiment report сам по себе не меняет active model, а лишь предоставляет evidence существующему activation gate. Текущий migration head — `0018_inference_observations`; migration обязательна, но переобучение active model не требуется, если его файл ещё доступен или уже имеет PostgreSQL archive.

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

По умолчанию проект может использовать динамический universe активных linear-инструментов. `UNIVERSE_MAX_SYMBOLS=0` означает отсутствие искусственного лимита после фильтрации. Криптовалютная модель исключает известные Bybit `symbolType` для TradFi-продуктов (`stock`, `forex`, `commodity`, `xstocks`/`xstock`); явный opt-in возможен только через `UNIVERSE_ALLOW_NON_CRYPTO_SYMBOL_TYPES=true`. Начиная с 1.29.0 каждый committed refresh записывает immutable eligibility snapshot. После обновления обязательно выполните `python manage.py migrate`; первые достоверные historical cross-section данные появляются только после первого успешного refresh.
Начиная с 1.30.0 dynamic training, trainer preflight и formal backtest используют только latest committed `dynamic` snapshot, доступный на соответствующий decision time; static-mode snapshots после переключения конфигурации не смешиваются с dynamic cohort. Pre-rollout строки исключаются, а stale/missing post-rollout evidence блокирует исследование. Поэтому сразу после обновления 1.29.0 накопленной истории может быть недостаточно для прежних minimum-history gates; это ожидаемое fail-closed поведение, а не повод снижать пороги.
Начиная с 1.31.0 latest-prior snapshots выбираются непосредственно PostgreSQL только для фактических hourly decision timestamps. Полный JSON evidence потоково перепроверяется, но в памяти остаются лишь `observed_at`, `recorded_at`, `selected_symbols`, `policy_hash` и `record_hash`. Это устраняет загрузку всего пятиминутного ledger за lookback без изменения point-in-time membership semantics.

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
7. для quality-passed inactive candidate preregister-ит и выполняет bounded experiment family либо использует явно заданную operator family;
8. активирует candidate только после absolute/relative quality gates и отдельного experiment promotion gate.

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

`python manage.py drift-report` создаёт `reports/production_drift.json`. Reference берётся из final holdout активного artifact; calibration baseline использует тот же selected-direction cohort, что и production outcomes. Начиная с 1.41.0 selected-cohort reference нельзя получить неявным переименованием all-direction матрицы: artifact обязан передать отдельные rows/log-loss/Brier выбранного policy-направления. Для calibration учитываются только сигналы с `event_time + horizon_hours <= report.generated_at`; ранние TP/SL незрелых сигналов исключаются, а любой unresolved mature signal даёт `incomplete_mature_outcome_coverage` и `BLOCKED`. Поле `outcome_coverage` раскрывает mature/resolved/unresolved counts и долю покрытия. PSI рассчитывается по фиксированным holdout-бинам. Failed inference jobs, недостаточная coverage/missingness или малая выборка также дают `BLOCKED`; `CRITICAL` и `BLOCKED` отображаются как `DEGRADED` в worker heartbeat. Поле `automatic_model_action` всегда равно `none`.

`python manage.py attrition-report -- --hours 168` создаёт `reports/candidate_live_attrition.json`. Отчёт объединяет background training attempts и hourly/catch-up inference за одно UTC-окно. Для live opportunities он дедуплицирует повторные попытки по `symbol × event_time`, показывает terminal skip reason либо наличие сигнала и отдельно считает восстановленные retries. Для каждого initial plan агрегируются status, terminal stage, primary и contributing reason codes; для training — failed attempts, quality-gate failures, activation и activation skips.

Report v3 загружает только exact `signal_id`/`plan_id` из instrumented jobs и добавляет `live.outcome_attribution`. Сигнал входит в сравнение только когда `event_time + horizon_hours <= until`; ранний TP/SL до полного horizon не используется. Для mature cohort показываются TP/SL/TIMEOUT, ambiguous count, coverage, valuation statuses и descriptive `counterfactual_r` по initial plan status/stage/reason. `counterfactual_r` доступен только для `VALUED` sized plans; `NO_TRADE`/blocked plans обычно имеют `NOT_SIZED`, поэтому для них честно остаются outcome counts без выдуманного R. Поля `actual_execution_pnl=false` и `causal_claim=false` запрещают трактовать отчёт как журнал реальных сделок или доказательство причинности. Missing mature signal/plan outcomes, label mismatch или invalid valuation/R pair переводят report в `BLOCKED`. Старые `JobRun` до prospective instrumentation не реконструируются. Daily report включает тот же раздел `candidate_live_attrition`.



## Временная семантика ML

Часовой feature row становится доступен только после закрытия исходной свечи. Dataset хранит:

- `source_open_time` — начало исходной свечи;
- `decision_time` — её закрытие и момент доступности признаков;
- `label_end_time` — закрытие последней свечи label horizon.

Train/calibration/final holdout формируются по `decision_time`; labels предыдущего окна обязаны завершиться раньше следующего окна. Stateful features сбрасывают состояние на gap, duplicate или невалидной OHLCV-свече; label-window с нечисловой/некогерентной ценой исключается. Decision anchor — close подтверждённой исходной свечи. Исполнимый proxy входа — direction-specific adverse half-spread вокруг `open` первой часовой свечи, начинающейся в `decision_time`. Research выбирает только `InstrumentSpecHistory`, у которого и `valid_from`, и `received_at` не позже decision time; будущая спецификация не может быть подставлена назад. Entry zone сначала сжимается до исполнимых тиков, затем LONG-entry округляется вверх, SHORT-entry вниз; LONG stop/TP округляются вниз, SHORT stop/TP вверх. Эти правила расширяют downside и не завышают upside относительно дискретной биржевой сетки. Если spec отсутствует, тик невалиден, зона не содержит исполнимого тика или барьер схлопывается, symbol-hour исключается с диагностикой. В live та же зона фиксируется вокруг decision close, а SL/TP и net economics считаются от фактического executable bid/ask только пока quote остаётся внутри зоны. Новые artifacts используют `feature_schema_version=hourly-barrier-market-context-v5`, `market_context_schema=hourly-oi-basis-settled-funding-turnover-v2`, `historical_funding_schema=bybit-settlement-timestamp-replay-v2`, `funding_interval_schedule_schema=instrument-spec-point-in-time-v1`, `label_path_schema_version=decision-open-directional-spread-tick-aligned-entry-ohlc-path-v4`, `entry_execution_model.schema=decision-close-tick-zone-next-hour-open-directional-half-spread-v3`, `temporal_split_schema=final-holdout-plus-expanding-walk-forward-v4` и `walk_forward_schema=expanding-train-rolling-calibration-purged-v1`. Runtime и promotion gate требуют новый schema contract; legacy artifacts нужно переобучить.

## Experiment-selection governance

Каждая backtest-оценка, дошедшая до валидированных artifact и final-test cohort, создаёт prospective trial в `research.experiment_events`. До расчёта записывается `STARTED` с canonical configuration hash; после расчёта — `SUCCEEDED` с выровненным почасовым return path либо `FAILED` с ограниченной диагностикой. События образуют SHA-256 hash chain и не заменяются mutable итоговой строкой. Повтор одной конфигурации учитывается как повторная попытка, но не как новый независимый вариант.

Каждый executable backtest обязан использовать точное имя заранее зарегистрированной `experiment_family`; автоматическое создание family из результата отключено. Все сравниваемые конфигурации должны иметь один и тот же timestamp grid. Затем выполните:

```bash
python manage.py experiment-report -- --family <exact-family-name>
```

Отчёт применяет contiguous combinatorially symmetric cross-validation для PBO, выбирает конфигурацию по non-annualized Sharpe и рассчитывает Deflated Sharpe probability с учётом skewness, kurtosis, числа зависимых trials и Newey–West effective observation count. Выбранный return path дополнительно получает Bartlett-HAC mean interval и moving-block intervals для mean/Sharpe; effective block length не может быть короче horizon. `READY` требует не только PBO/DSR thresholds, но и положительные нижние dependence-aware bounds. `STARTED` без terminal event, unresolved `FAILED`, недостаток blocks/trials/periods, несовпадающие timestamps или повреждённая hash chain дают `BLOCKED_*`. Сам `experiment-report` не изменяет registry state и сохраняет `profitability_claimed=false`; normal activation отдельно потребляет и повторно проверяет его evidence.

Evidence trial ledger накапливается только после migration 1.18.0, formal family preregistration — после 1.20.0, а verified UI exposure — после 1.21.0. Старые backtests и pre-1.20 families не backfill-ятся как preregistered evidence; pre-1.21 unexposed plans не считаются пропущенными exposures. Propensity bootstrap остаётся условным на уже fitted OOS scores, external trusted timestamp отсутствует, а experiment report не является promotion gate active model.

## Research backtest

Backtest загружает artifact через тот же runtime validator, что и production; при необходимости `--model-sha256` фиксирует ожидаемый hash. Research dataset атомарно создает ровно одну LONG- и одну SHORT-строку на symbol/timestamp и сохраняет `entry_price` для аудита; если геометрия хотя бы одного направления невалидна, исключается весь cohort. До выбора направления все строки проверяются на допустимый target, finite barrier/return, exit index и доступность label; поврежденная проигравшая строка не может исчезнуть из проверки. Temporal split, holdout policy и backtest повторно проверяют этот контракт fail-closed. После проверки backtest выбирает не более одного направления по тому же порядку policy, что и production: максимальный net `EV/R`, затем net RR и детерминированный LONG tie-break. Runtime, holdout policy, backtest и Decimal risk math отвергают probabilities вне диапазона `[0, 1]`, с неединичной суммой либо нечисловыми значениями. Комиссия каждой ноги считается от фактического входного/выходного notional; slippage, stop-gap reserve, статический funding-сценарий и policy-пороги задаются отдельно. Исторический research replay учитывает только settlement events в окне `(entry_time, actual_exit_time]`; положительный exchange funding означает расход LONG и доход SHORT. Будущая фактическая ставка не используется для ex-ante выбора направления. CLI `--funding-rate` остаётся отдельным неблагоприятным stress-сценарием для ожидаемой экономики и не переписывает realized historical cash flow.

Для горизонта `H` часов капитал делится на `H` равных sleeves. Часовой cohort использует один sleeve и этот капитал не переиспользуется до завершения максимального label horizon. Средние promotion-метрики рассчитываются сначала внутри каждого реально наблюдавшегося hourly decision cohort; количество символов в одном часу не создаёт дополнительные независимые наблюдения. Если во всём таком cohort policy отвергла сделки, его реализованная и ожидаемая policy-доходность равна нулю. Отсутствующие рыночные часы не синтезируются. Метрики отдельно раскрывают `policy_trade_cohorts` и `policy_no_trade_cohorts`. Для uncertainty gate полный opportunity path разбивается на `H` epoch-hour phases, каждая из которых содержит неперекрывающиеся label windows. Фазы балансируются до одинаковой недавней длины, а gate использует минимальные phase mean и phase LCB, поэтому inference не зависит от первого timestamp holdout и не условна на собственном выборе сделок. Auto-activation требует минимум raw trades, независимых opportunity cohorts и `policy_trade_rate >= AUTO_TRAIN_MIN_POLICY_TRADE_RATE` (default 1%). Доля пересчитывается как `policy_trades / policy_candidates` и проверяется на внутреннюю согласованность; final holdout обязан содержать ровно две directional строки на одну policy opportunity, а selected-direction calibration — ровно одну строку на opportunity; malformed или статистически микроскопическая policy блокируется fail-closed. Gross gain и gross loss для profit factor суммируются по отдельным trade contributions до агрегации по времени выхода; одновременные прибыль и убыток не взаимопогашаются. Положительный holdout без отрицательных trade contributions представляет profit factor как математически неограниченный только при явных `gross_gain > 0` и `gross_loss = 0`; отсутствие сделок или неполные метрики остаются fail-closed. Дополнительно research-поток применяет live-инвариант «не более одного активного плана на symbol в одном account scope»: следующий кандидат того же символа исключается до modeled exit предыдущего, а вход ровно на границе выхода разрешён. Число исключённых кандидатов публикуется как `overlap_blocked_trades` / `policy_overlap_blocked_trades`. Поэтому перекрывающиеся H-часовые returns не компаундятся как последовательные одночасовые сделки, не создают скрытое H-кратное плечо и не завышают promotion evidence сделками, которые live acceptance отклонил бы. PnL зачисляется в equity curve в modeled candle exit time. Метрики concurrency считают реально открытые позиции, а не только новые входы в один timestamp.

`net_return` отражает наблюдаемый gross outcome за вычетом фактических модельных fee/slippage/funding и не списывает неиспользованный stop-gap reserve как денежный убыток. Любой состоявшийся gap уже находится в `realized_gross_return`. Консервативный остаточный reserve остаётся в downside для sizing/actionability и отдельно публикуется как `stress_net_return_with_stop_gap_reserve`; legacy-поле `net_return_without_stop_gap_reserve` сохранено как совместимый alias фактического `net_return`.

Research backtest моделирует realized-only intrahorizon mark-to-market по точной hourly Bybit mark-price OHLC timeline, учитывает фактически пересечённые funding settlements и консервативно ставит liquidation touch раньше более позднего неупорядоченного last-price TP/SL touch в том же bar. Для каждого decision/settlement используется funding interval из point-in-time `InstrumentSpecHistory`; стабильные участки проверяются точно, а переходы interval — консервативно по наблюдаемой event cadence. Симулятор остаётся isolated-margin research proxy: он не реконструирует sub-hour mark path, исторические maintenance-margin/risk-tier изменения, liquidation fees, cross/portfolio margin, ADL, страховой фонд или точный fill. Полный historical order book, queue position и historical fill/latency trajectory до 1.14.0 отсутствуют. Prospective depth/VWAP/FULL-PARTIAL-NO_FILL и operator-latency evidence накапливается только с 1.14.0; historical funding forecast snapshots и интервалы до первой локально наблюдаемой spec-записи по-прежнему не реконструируются.
Эти ограничения означают, что прохождение unit tests или promotion gate не подтверждает live-edge: historical entry остаётся next-hour open proxy, а live plan использует executable bid/ask внутри ограниченной decision-time зоны и ручное решение оператора. Задержка внутри разрешённого окна, sub-hour path, queue position и фактический fill всё ещё не реконструируются. Release 1.14.0 начал накапливать point-in-time liquidity snapshots и operator-latency evidence; release 1.15.0 добавил prospective selection ledger; release 1.22.0 устранил применение последнего funding interval ко всей наблюдаемой истории; release 1.23.0 устранил right-censoring calibration drift незрелыми early-exit outcomes. До появления достаточной forward-истории, historical funding-forecast snapshots, подтверждённых pre-observation interval records и более детальной queue/fill траектории разрыв должен считаться существенным модельным риском.

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
- Research validation использует трёхфолдовый purged expanding walk-forward внутри development period и отдельный final holdout. Prospective trial ledger, formal family preregistration, contiguous CSCV/PBO, HAC-adjusted DSR, dependence-aware intervals, production drift monitoring и bounded automatic RR/EV family для background candidate реализованы как governance layers. Nested hyperparameter selection, conditional search-space schemas, studentized bootstrap и адаптивное расширение experiment grid отсутствуют; activation по-прежнему выполняется отдельным exact-artifact/policy gate, а не самим отчётом.
- Intrahorizon mark-to-market реализован как conservative hourly mark-price isolated-margin proxy; exact sub-hour path, historical MMR/risk tiers, cross/portfolio margin и liquidation fees отсутствуют.
- Техническая корректность расчётов и тестов не означает наличия статистически устойчивого торгового преимущества.
