# Patch 1.1.2 — Windows asyncio / psycopg

Исправлена несовместимость асинхронного psycopg с `ProactorEventLoop`, который Python 3.12 выбирает в Windows по умолчанию.

## Симптом

Команда `py -3.12 manage.py migrate` завершалась ошибкой:

```text
Psycopg cannot use the 'ProactorEventLoop' to run in async mode
```

Та же проблема могла проявиться при запуске API, worker, обучения, backtest и отчетов.

## Исправление

Alembic переведен на синхронное подключение psycopg и больше вообще не создает event loop. Для остальных асинхронных процессов проект на Windows до загрузки движка БД устанавливает `WindowsSelectorEventLoopPolicy`. На Linux и macOS функция ничего не меняет; вызов идемпотентный.

Изменены:

- `app/asyncio_compat.py` — единая платформенная настройка;
- `app/__init__.py` — ранняя активация до импорта движка БД;
- `migrations/env.py` — синхронный migration runner без зависимости от Windows event loop;
- `tests/unit/test_asyncio_compat.py` — регрессионные тесты;
- версия проекта — `1.1.2`.

Docker не добавлялся.
