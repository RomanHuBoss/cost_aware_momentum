# Конфигурация

Все параметры задаются через `.env`. PostgreSQL обязателен; при недоступной БД API не становится ready и не переключается на файловое хранилище.

## Приложение и доступ

| Переменная | Назначение | Рекомендуемое значение |
|---|---|---|
| `APP_MODE` | `development`, `backtest`, `paper`, `shadow`, `production` | `paper` до завершения forward-проверки |
| `APP_HOST`, `APP_PORT` | адрес API | `127.0.0.1:8000` |
| `SECRET_KEY` | подпись сессий | случайная строка не менее 32 байт |
| `OPERATOR_PASSWORD` | локальный вход | уникальный длинный пароль |
| `OPERATOR_API_TOKEN` | альтернативный токен для CLI | пусто, если не нужен |
| `COOKIE_SECURE` | Secure cookie | `true` за HTTPS |
| `ALLOW_DEMO_SEED` | разрешение demo seed | `false` в production |

`python manage.py configure` генерирует `SECRET_KEY` и запрашивает пароль оператора без вывода его в консоль.

## PostgreSQL

`DATABASE_URL` должен иметь схему `postgresql+psycopg://` или `postgresql://` и указывать на локальную или выделенную PostgreSQL-службу. Разные среды используют отдельные базы или кластеры. Схема проверяется Alembic; несовпадение revision блокирует readiness.

Пример локального подключения:

```text
postgresql+psycopg://cost_momentum:СЛОЖНЫЙ_ПАРОЛЬ@localhost:5432/cost_momentum
```

`POSTGRES_ADMIN_URL` является необязательным. Он нужен только для автоматического создания базы, тестового восстановления и временных integration-test databases. По возможности задавайте его как переменную окружения непосредственно перед командой и удаляйте после выполнения.

`TEST_DATABASE_URL` позволяет указать заранее созданную отдельную тестовую базу. Никогда не направляйте integration-тесты на рабочую базу.

## Bybit

`BYBIT_BASE_URL` по умолчанию указывает на основной V5 API. `BYBIT_API_KEY` и `BYBIT_API_SECRET` нужны только для read-only equity/positions/fees. `BYBIT_READ_ONLY_ACCOUNT=true` включает приватные GET-запросы. Ключ с торговыми или withdrawal-правами не требуется.

## Universe и данные

`UNIVERSE_MODE=dynamic` включает полный динамический сканер Bybit. Worker получает все страницы `instruments-info` для категории `linear`, затем одним запросом получает tickers по всей категории и формирует исполнимый universe из активных USDT-settled `LinearPerpetual` контрактов. `SYMBOLS` используется только при `UNIVERSE_MODE=static`.

Фильтры динамического universe:

| Переменная | Назначение |
|---|---|
| `UNIVERSE_MIN_AGE_DAYS` | минимальный возраст листинга |
| `UNIVERSE_MIN_TURNOVER_24H` | минимальный 24-часовой оборот в USDT; `0` отключает фильтр |
| `UNIVERSE_MAX_SPREAD_BPS` | максимальный bid/ask spread в базисных пунктах; `0` отключает фильтр |
| `UNIVERSE_MAX_SYMBOLS` | top-N по обороту; `0` означает все прошедшие фильтры |
| `UNIVERSE_REFRESH_SECONDS` | период пересборки состава universe |
| `UNIVERSE_MIN_HISTORY_BARS` | минимум подтвержденных часовых свечей перед inference |
| `UNIVERSE_EXCLUDED_SYMBOLS` | точечный blacklist символов |
| `UNIVERSE_EXCLUDED_BASE_COINS` | исключаемые базовые активы, например stablecoins |
| `UNIVERSE_ALLOW_NON_CRYPTO_SYMBOL_TYPES` | разрешать ли non-crypto/TradFi symbol types |
| `UNIVERSE_SYNC_MARK_PRICE` | дополнительно сохранять mark-price candles |
| `UNIVERSE_ENRICH_FUNDING_OI` | выполнять тяжелый исторический сбор funding/OI для каждого нового участника |
| `TICKER_RETENTION_HOURS` | срок хранения минутных ticker snapshots |
| `INITIAL_BACKFILL_BARS` | быстрый стартовый срез свечей для нового символа; default 1000 |
| `HISTORY_BACKFILL_ENABLED` | постепенно расширять исторические свечи назад |
| `HISTORY_BACKFILL_TARGET_DAYS` | целевая глубина истории; default 365 дней |
| `HISTORY_BACKFILL_INTERVAL_SECONDS` | частота небольших backfill-циклов |
| `HISTORY_BACKFILL_SYMBOLS_PER_CYCLE` | сколько символов углублять за один цикл |
| `HISTORY_BACKFILL_PAGES_PER_SYMBOL` | максимум страниц Bybit за символ и цикл |
| `HISTORY_BACKFILL_PAGE_SIZE` | размер страницы Bybit, не более 1000 |
| `OUTCOME_INTRABAR_INTERVAL` | интервал `1`, `3` или `5` минут для разрешения hourly TP/SL ambiguity; default `5` |
| `OUTCOME_INTRABAR_MAX_WINDOWS_PER_CYCLE` | максимум точечных intrabar windows за один outcome cycle; default `100` |

`UNIVERSE_MAX_SYMBOLS=0` не означает отсутствие фильтра качества: система сканирует полный биржевой каталог, но анализирует только контракты, прошедшие статус, тип, возраст, ликвидность, spread и data-quality checks. Это предотвращает смешивание «всех существующих тикеров» с реально исполнимым торговым universe.

При первом включении dynamic mode worker загружает быстрый стартовый срез для всех отобранных символов. Затем отдельный job `history_backfill` постепенно запрашивает более старые страницы до целевой глубины, не блокируя API и часовой inference на длительное время. Для молодых контрактов целевая дата автоматически ограничивается временем листинга. Далее tickers обновляются с частотой `MARKET_POLL_SECONDS`, состав universe — с частотой `UNIVERSE_REFRESH_SECONDS`, а свечи всех активных символов обновляются один раз после закрытия часа перед inference. Незакрытая REST-свеча сохраняется с `confirmed=false` и не входит в признаки.

Для counterfactual evaluation 1/3/5-минутные свечи не загружаются по всему universe. Worker сначала обнаруживает конкретный час, где hourly high/low одновременно пересекли TP1 и SL, затем выполняет один ограниченный public/read-only запрос только для этого symbol/time window. Неполный ответ не заменяется предположением: outcome остается pending до получения непрерывного intrabar path. Лимит windows на цикл защищает worker от большого backlog и API burst.

## Risk policy

- `DEFAULT_RISK_RATE`: базовый риск на сделку, по умолчанию 0,35%.
- `MAX_TOTAL_OPEN_RISK_RATE`: общий stop-risk портфеля.
- `DEFAULT_LEVERAGE`: базовое плечо 3x.
- `MAX_LEVERAGE`: жесткий предел 5x в приложении.
- `MARGIN_RESERVE_RATE`: доля свободной маржи, недоступная sizing engine.
- `MIN_NET_RR`, `MIN_NET_EV_R`: policy thresholds после издержек.
- `MAX_SPREAD_BPS`: блокирующий/предупреждающий лимит спреда.
- `FEE_RATE_TAKER`, `BASE_SLIPPAGE_BPS`, `STOP_GAP_RESERVE_BPS`: консервативная модель издержек.

Риск нельзя свободно менять на плитке. Изменение профиля создает новую версию execution plan и не переписывает исторические расчеты.

## Model runtime

| Переменная | Назначение |
|---|---|
| `MODEL_DIR` | каталог immutable joblib artifacts |
| `ACTIVE_MODEL_PATH` | аварийный явный override; обычно оставляется пустым |
| `ALLOW_BASELINE_MODEL` | разрешить некалиброванную операционную заглушку |
| `MODEL_REFRESH_SECONDS` | период перечитывания active model registry worker |
| `HORIZONS_HOURS` | разрешенные горизонты обучения |
| `DEFAULT_HORIZON_HOURS` | горизонт, которому должна соответствовать active live-модель |

Нормальный источник active model — таблица `model.model_registry`. Обучение сохраняет SHA256 и регистрирует artifact inactive. Команда `model-registry activate` проверяет file/hash/version/task/schema/classes/horizon, деактивирует предыдущую версию и создает audit/outbox event. Worker повторяет проверку при загрузке.

`ACTIVE_MODEL_PATH` сохранен только как явный operational override и также проходит строгую проверку. Он не должен скрытно расходиться с registry в штатной эксплуатации.

В `production` validator требует `ALLOW_BASELINE_MODEL=false`, `ALLOW_DEMO_SEED=false`, измененные `SECRET_KEY` и `OPERATOR_PASSWORD`. При отсутствии валидной active-модели worker не стартует корректно, а readiness остается false.

## Background trainer

`python manage.py run` запускает trainer отдельным процессом рядом с API и inference worker. Тяжелое обучение выполняется вне request path и не задерживает публикацию часовых рекомендаций.

| Переменная | Назначение |
|---|---|
| `AUTO_TRAIN_ENABLED` | запускать ли фоновый trainer |
| `AUTO_TRAIN_AUTO_ACTIVATE` | автоматически активировать только кандидата, прошедшего quality gate |
| `AUTO_TRAIN_MODEL_TYPE` | `logistic` или `hist_gradient_boosting` |
| `AUTO_TRAIN_INTERVAL_HOURS` | минимальный интервал между успешными циклами обучения; default 168 часов |
| `AUTO_TRAIN_RETRY_HOURS` | пауза после ошибки обучения |
| `AUTO_TRAIN_CHECK_SECONDS` | частота проверки расписания и достаточности данных |
| `AUTO_TRAIN_INITIAL_DELAY_SECONDS` | задержка первого фонового запуска после старта системы |
| `AUTO_TRAIN_LOOKBACK_DAYS` | rolling-окно подтвержденных свечей, используемое для переобучения |
| `AUTO_TRAIN_MAX_SYMBOLS` | top-N символов по последнему 24h turnover для ограничения памяти; `0` использует все сохраненные символы |
| `AUTO_TRAIN_MIN_NEW_TIMESTAMPS` | сколько новых часовых timestamps требуется после `training_end` active-модели |
| `AUTO_TRAIN_DATA_CHANGE_COOLDOWN_HOURS` | короткий cooldown для переобучения после крупного backfill/universe change |
| `AUTO_TRAIN_MIN_NEW_ROWS` | минимальный абсолютный прирост trainable candle rows |
| `AUTO_TRAIN_MIN_DATASET_GROWTH_RATIO` | минимальный относительный прирост датасета |
| `AUTO_TRAIN_MIN_NEW_SYMBOLS` | сколько новых покрытых символов считается существенным изменением |
| `AUTO_TRAIN_MIN_UNIVERSE_CHANGE_RATIO` | порог изменения состава обучающего universe |
| `AUTO_TRAIN_MIN_BARS_PER_SYMBOL` | минимальная глубина символа для coverage check |
| `AUTO_TRAIN_MIN_SYMBOL_COVERAGE_RATIO` | минимальная доля top-N символов с достаточной глубиной |
| `AUTO_TRAIN_MIN_HOLDOUT_ROWS` | минимальный размер нового final holdout |
| `AUTO_TRAIN_MIN_CLASS_FRACTION` | минимальная доля каждого исхода TP/SL/TIMEOUT в holdout |
| `AUTO_TRAIN_MAX_LOG_LOSS` | абсолютный верхний предел log loss кандидата |
| `AUTO_TRAIN_MAX_MULTICLASS_BRIER` | абсолютный верхний предел multiclass Brier |
| `AUTO_TRAIN_MAX_ECE` | верхний предел ECE по каждому outcome |
| `AUTO_TRAIN_MAX_LOG_LOSS_REGRESSION` | допустимое ухудшение log loss относительно active-модели на том же holdout |
| `AUTO_TRAIN_MAX_BRIER_REGRESSION` | допустимое ухудшение Brier относительно active-модели |
| `AUTO_TRAIN_MIN_METRIC_IMPROVEMENT` | минимальное улучшение хотя бы одной основной метрики |
| `AUTO_TRAIN_MIN_POLICY_TRADES` | минимум cost-aware сделок на общем holdout |
| `AUTO_TRAIN_MIN_POLICY_REALIZED_MEAN_R` | минимальный средний реализованный результат в R |
| `AUTO_TRAIN_MIN_POLICY_PROFIT_FACTOR` | минимальный holdout profit factor |
| `AUTO_TRAIN_MAX_POLICY_DRAWDOWN_R` | максимальная допустимая просадка holdout policy в R |
| `AUTO_TRAIN_MAX_POLICY_MEAN_R_REGRESSION` | допустимое ухудшение mean R относительно incumbent |
| `AUTO_TRAIN_MAX_POLICY_DRAWDOWN_REGRESSION_R` | допустимое ухудшение drawdown относительно incumbent |
| `AUTO_TRAIN_MIN_POLICY_IMPROVEMENT_R` | улучшение mean R, достаточное для relative gate |
| `AUTO_TRAIN_REQUIRE_IMPROVEMENT` | требовать ли улучшение перед автоматической активацией |
| `TRAINER_ID` | идентификатор trainer heartbeat и job actor |

Trainer не изменяет существующий artifact на месте. Он полностью переобучает candidate на актуальном rolling-окне, сохраняет его атомарно, регистрирует SHA256 и сравнивает candidate с incumbent на одном и том же новом holdout. Начиная с 1.7.1 все model/trainer JSONB payload нормализуются в строгий JSON; `NaN` и `±Infinity` не допускаются, а отсутствующие метрики хранятся как `null`. Каждый artifact хранит полный dataset profile: candle rows, timestamps, список символов, временные границы, coverage и SHA256-подписи состава/покрытия. Поэтому существенная загрузка старой истории запускает переобучение даже при одном новом часовом timestamp. Не прошедший quality gate artifact остается неактивным. При конкурентном запуске используется PostgreSQL session advisory lock; при смене active-модели во время оценки auto-activation отменяется.

`ACTIVE_MODEL_PATH` считается аварийным override. При его наличии trainer продолжает формировать candidates, но не выполняет автоматическую активацию registry-модели, поскольку inference worker все равно предпочитает override.
