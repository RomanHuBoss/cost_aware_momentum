# Cost-aware hourly ML momentum

> Версия 1.8.4: LONG/SHORT теперь выбирается по той же чистой экономике `EV/R`, которая публикуется оператору и используется policy quality gate, а не по предварительной беззатратной utility модели.

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
- Fail-closed при stale/invalid data, несовместимом artifact, нарушенной геометрии или превышении риска.
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
- Положительный funding: LONG платит, SHORT получает; отрицательный funding меняет знак.
- Stop-gap reserve относится к downside.
- Leverage меняет margin requirement, но не экономический edge на notional.
- Quantity округляется вниз по `qtyStep`; после округления повторно проверяются risk, margin, `minQty` и `minNotional`.
- Безопасный размер ниже биржевого минимума блокируется и не округляется вверх.

## Временная семантика ML

Часовой feature row становится доступен только после закрытия исходной свечи. Dataset хранит:

- `source_open_time` — начало исходной свечи;
- `decision_time` — её закрытие и момент доступности признаков;
- `label_end_time` — закрытие последней свечи label horizon.

Train/calibration/final holdout формируются по `decision_time`; labels предыдущего окна обязаны завершиться раньше следующего окна. Новые artifacts используют `feature_schema_version=hourly-barrier-contiguous-v3` и `temporal_split_schema=decision-and-label-end-purged-v3`.

## Research backtest

Backtest выбирает не более одного направления на символ и timestamp. Одновременные позиции сначала агрегируются в один равновзвешенный портфельный return за timestamp и только затем компаундятся. Equity curve начинается с исходного капитала `1.0`, поэтому просадка первой сделки не теряется.

Research backtest не моделирует полный historical order book, partial fills и задержку оператора и не является доказательством прибыльности.

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

## Обновление с 1.8.3 на 1.8.4

- DB migration не требуется.
- Новые `.env` переменные не требуются.
- Перезапустите API, worker и trainer после замены файлов.
- Переобучение artifact не требуется: контракт `TP / SL / TIMEOUT` не изменился.
- После перезапуска worker оценивает оба направления и публикует сценарий с максимальным текущим net `EV/R`; поэтому направление части рекомендаций может корректно отличаться от 1.8.3.

## Ограничения

- Нет автоматического исполнения ордеров.
- Ручные fills остаются источником фактической информации об исполнении.
- Техническая корректность расчётов и тестов не означает наличия статистически устойчивого торгового преимущества.
