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

`UNIVERSE_MAX_SYMBOLS=0` не означает отсутствие фильтра качества: система сканирует полный биржевой каталог, но анализирует только контракты, прошедшие статус, тип, возраст, ликвидность, spread и data-quality checks. Это предотвращает смешивание «всех существующих тикеров» с реально исполнимым торговым universe.

При первом включении dynamic mode worker выполняет backfill часовых свечей для всех отобранных символов. Далее tickers обновляются с частотой `MARKET_POLL_SECONDS`, состав universe — с частотой `UNIVERSE_REFRESH_SECONDS`, а свечи всех активных символов обновляются один раз после закрытия часа перед inference. Незакрытая REST-свеча сохраняется с `confirmed=false` и не входит в признаки.

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

`MODEL_DIR` по умолчанию равен относительному каталогу `models`. `ACTIVE_MODEL_PATH` указывает на joblib-артефакт. SHA256 сохраняется при обучении. При отсутствии артефакта и `ALLOW_BASELINE_MODEL=true` запускается детерминированный baseline с явным предупреждением. Для production рекомендуется `ALLOW_BASELINE_MODEL=false`.
