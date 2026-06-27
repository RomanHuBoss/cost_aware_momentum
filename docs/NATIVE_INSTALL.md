# Нативная установка и эксплуатация

## 1. Компоненты

Приложение состоит из трех постоянно работающих компонентов:

1. локальная служба PostgreSQL;
2. FastAPI/Uvicorn API с web-интерфейсом;
3. отдельный worker сбора рынка и часового inference.

API и worker используют одну `.env`, но являются отдельными процессами. `python manage.py run` запускает оба процесса и корректно останавливает их по `Ctrl+C`.

## 2. Windows

### Установка зависимостей системы

- Python 3.12 x64 с включенной опцией добавления Python в `PATH`;
- PostgreSQL 16/17 с Command Line Tools;
- каталог вида `C:\Program Files\PostgreSQL\17\bin` в пользовательском или системном `PATH`.

Проверка:

```powershell
py -3.12 --version
psql --version
pg_dump --version
pg_restore --version
```

### Подготовка приложения

```powershell
py -3.12 manage.py setup
py -3.12 manage.py configure
py -3.12 manage.py db-init
py -3.12 manage.py migrate
py -3.12 manage.py doctor
```

### Запуск

```powershell
py -3.12 manage.py run
```

Для раздельного запуска откройте два PowerShell-окна:

```powershell
py -3.12 manage.py api
```

```powershell
py -3.12 manage.py worker
```

## 3. Linux

Установите Python, PostgreSQL server/client и build tools штатным менеджером пакетов. Запустите службу PostgreSQL. При локальной peer-аутентификации роль и базу удобнее создать от системного пользователя `postgres`.

```bash
sudo -u postgres psql
```

```sql
CREATE ROLE cost_momentum LOGIN PASSWORD 'СЛОЖНЫЙ_ПАРОЛЬ';
CREATE DATABASE cost_momentum OWNER cost_momentum;
```

После этого укажите тот же пароль в `DATABASE_URL`, примените миграции и запустите диагностику.

## 4. macOS

Установите Python 3.12 и PostgreSQL 16/17, запустите PostgreSQL как системную службу. Дальнейшие команды совпадают с Linux. Проверьте, что каталог PostgreSQL `bin` присутствует в `PATH`.

## 5. Запуск при старте операционной системы

Для постоянной эксплуатации рекомендуется запускать API и worker как две независимые службы с одной рабочей директорией и одной `.env`.

### Windows Task Scheduler

Создайте три задачи с действием:

```text
<PROJECT>\.venv\Scripts\python.exe -m app.main
```

```text
<PROJECT>\.venv\Scripts\python.exe -m app.workers.runner
```

```text
<PROJECT>\.venv\Scripts\python.exe -m app.workers.trainer
```

Рабочий каталог всех задач должен быть равен корню проекта. Trainer можно не создавать, если `AUTO_TRAIN_ENABLED=false`. Запускайте задачи от отдельной локальной учетной записи с минимальными правами.

### systemd

Создайте отдельные unit-файлы для `app.main`, `app.workers.runner` и `app.workers.trainer`. Укажите `WorkingDirectory`, путь к Python из `.venv`, автоматический restart при ошибке и зависимость от `postgresql.service` и сети.

## 6. Обновление

1. Остановить API, worker и trainer.
2. Создать резервную копию: `python manage.py backup`.
3. Обновить файлы проекта.
4. Выполнить `python manage.py setup` для синхронизации зависимостей.
5. Выполнить `python manage.py migrate`.
6. Выполнить `python manage.py doctor`.
7. Запустить API, worker и trainer.

## 7. Резервное копирование

```bash
python manage.py backup
python manage.py restore-check
```

Первая команда создает custom-format dump. Вторая создает временную базу, восстанавливает dump, проверяет основные таблицы и удаляет временную базу. Для создания временной базы требуется административное подключение через `POSTGRES_ADMIN_URL` либо право `CREATEDB` у пользователя приложения.

## Примечание для Windows и psycopg

Версия 1.1.3 запускает FastAPI, worker и остальные асинхронные CLI-команды через явный selector-based event loop на Windows. Это не зависит от выбора loop внутри Uvicorn и совместимо с async psycopg. Дополнительные команды или ручная настройка `asyncio` не требуются.
