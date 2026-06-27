# QA report

Дата повторной проверки нативной версии 1.2.1: 27 июня 2026 г.

## Выполненные проверки

| Проверка | Результат |
|---|---|
| `ruff check app scripts tests migrations manage.py` | Пройдена без замечаний |
| `python -m compileall -q app scripts migrations tests manage.py` | Пройдена |
| `pytest tests/unit -q` | 36 unit-тестов пройдены |
| Проверка версии пакета | `1.2.1` |
| Поиск Docker/Compose-файлов | Запрещенная контейнерная конфигурация отсутствует |


## Динамический universe 1.2.1

Проверено, что dynamic mode:

1. загружает полный список `linear` инструментов с пагинацией;
2. допускает только `Trading`, `LinearPerpetual`, USDT-settled и не pre-listing контракты;
3. применяет возраст, turnover и spread filters;
4. исключает stablecoin-base и только явно идентифицированные xStocks; региональное поле `symbolType` больше не трактуется как crypto/non-crypto classifier;
5. ранжирует по 24h turnover и корректно обрабатывает `UNIVERSE_MAX_SYMBOLS=0` как отсутствие top-N cap;
6. выполняет backfill только для новых участников и часовое обновление свечей перед inference;
7. передает активный состав в inference, train и backtest;
8. публикует counts и причины исключения в status/job metadata;
9. выполняет catch-up inference после стартового backfill и при расширении universe;
10. UI запрашивает до 2000 рекомендаций и показывает selected/eligible/card counts.

## Регрессия Windows/Python 3.12

Исправлен точный класс сбоя:

```text
Psycopg cannot use the 'ProactorEventLoop' to run in async mode
```

Причина повторного сбоя версии 1.1.2: одной установки `WindowsSelectorEventLoopPolicy` оказалось недостаточно. Новые версии Uvicorn могут явно создавать `ProactorEventLoop` в собственном runner и тем самым обходить глобальную policy.

Версия 1.1.3 применяет более жесткое решение:

1. Alembic выполняет online migrations через синхронный SQLAlchemy engine с драйвером psycopg.
2. FastAPI запускается через `uvicorn.Server(...).serve()`, но asyncio runner принадлежит проекту, а не Uvicorn.
3. На Windows runner напрямую создает `SelectorEventLoop` через `loop_factory`.
4. Worker, train, backtest, replay и daily report используют тот же совместимый runner.
5. Глобальная selector policy сохранена как дополнительный слой совместимости для стороннего кода.

Добавлены пять тестов платформенной совместимости: no-op вне Windows, замена policy, идемпотентность, прямое создание selector loop и передача явной loop factory в runner.

## Регрессия конфигурации версии 1.1.1

Сохранена поддержка обоих форматов списков в `.env`:

```env
SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT
HORIZONS_HOURS=4,8,12
```

и:

```env
SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT"]
HORIZONS_HOURS=[4,8,12]
```

## PostgreSQL integration tests

Два теста требуют работающей PostgreSQL и отдельной тестовой базы. Строгая локальная приемка:

```powershell
$env:POSTGRES_ADMIN_URL="postgresql+psycopg://postgres:ПАРОЛЬ@localhost:5432/postgres"
py -3.12 manage.py test --require-integration
Remove-Item Env:POSTGRES_ADMIN_URL
```

## Обязательная приемка перед эксплуатацией

1. Выполнить `py -3.12 manage.py migrate`.
2. Выполнить `py -3.12 manage.py doctor`.
3. Выполнить строгие integration-тесты с отдельной тестовой базой.
4. Запустить `py -3.12 manage.py run` и проверить `/health/ready`.
5. Проверить worker heartbeat и public Bybit ingestion.
6. Выполнить backup и restore-check.
7. Провести paper/shadow период; наличие работающего кода не доказывает прибыльность стратегии.

## Граница безопасности

Bybit-клиент содержит только public и private read-only запросы. Endpoint создания, изменения, отмены ордеров и вывода средств отсутствуют.
