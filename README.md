# Cost-aware hourly ML momentum


> Версия 1.7.9: multiclass `log_loss` теперь вычисляется строго в объявленном порядке классов `TP / SL / TIMEOUT`, без скрытой лексикографической перестановки столбцов scikit-learn. В metrics дополнительно сохраняются raw/calibrated log loss и сравнение с class-prior/uniform benchmark.

Локальная рекомендательная система для линейных USDT-фьючерсов Bybit. Система получает рыночные данные, строит часовые признаки, формирует LONG/SHORT-кандидаты, учитывает комиссии, проскальзывание, funding, риск и портфельные ограничения, а затем показывает оператору исполнимый план. Ордеры на биржу приложение **не отправляет**.

Проект запускается нативно: Python-процессы API, inference worker и background trainer работают непосредственно в операционной системе, PostgreSQL устанавливается как локальная системная служба. SQLite и файловый fallback отсутствуют.

## Состав проекта

- FastAPI/Uvicorn: versioned REST API, аутентификация, CSRF, SSE, health/readiness.
- PostgreSQL: единственный источник истины во всех режимах.
- Worker: справочники Bybit, свечи, tickers, funding/OI, read-only account snapshots, часовой inference, expiry/reconciliation.
- Trainer: фоновое периодическое переобучение, quality gate, регистрация кандидата, безопасная auto-activation и heartbeat.
- ML/research: direction-conditional TP/SL/TIMEOUT модели, отдельная временная калибровка, purge/final holdout, registry activation и barrier-policy backtest CLI.
- Risk engine: net R/R, net EV, комиссии, funding, stress-downside, sizing, margin/liquidity/portfolio/min-order checks.
- Operator UI: компактные плитки, профиль капитала, подробный диалог, словарь подсказок, accept/reject и журнал ручных сделок.
- Audit: append-only hash chain, idempotency keys, outbox events, job runs и service heartbeats.

## Требования

- Python 3.12 или новее.
- PostgreSQL 16 или 17 вместе с утилитами `psql`, `pg_dump` и `pg_restore`.
- Доступ к интернету для установки Python-зависимостей и получения данных Bybit.
- Node.js нужен только для дополнительной проверки синтаксиса frontend-кода; для работы приложения не требуется.

## Быстрый запуск на Windows

1. Установите Python 3.12 x64 и PostgreSQL. При установке PostgreSQL запомните пароль пользователя `postgres` и добавьте каталог `bin` PostgreSQL в `PATH`.
2. Откройте PowerShell в каталоге проекта.

```powershell
py -3.12 manage.py setup
py -3.12 manage.py configure
py -3.12 manage.py db-init
py -3.12 manage.py migrate
py -3.12 manage.py doctor
py -3.12 manage.py run
```

`configure` безопасно создаст новый `SECRET_KEY` и запросит пароль оператора. `db-init` запросит пароль локального администратора PostgreSQL и создаст прикладную роль и базу из `DATABASE_URL`.

После запуска откройте:

```text
http://127.0.0.1:8000
```

Остановка API, inference worker и trainer выполняется сочетанием `Ctrl+C` в окне запуска.

## Быстрый запуск на Linux/macOS

Сначала установите Python и PostgreSQL штатным менеджером пакетов операционной системы, запустите службу PostgreSQL и убедитесь, что `psql`, `pg_dump` и `pg_restore` доступны в `PATH`.

```bash
python3.12 manage.py setup
python3.12 manage.py configure
python3.12 manage.py db-init
python3.12 manage.py migrate
python3.12 manage.py doctor
python3.12 manage.py run
```

При peer-аутентификации Linux базу можно создать вручную от системного пользователя PostgreSQL, после чего выполнить только миграции:

```bash
sudo -u postgres psql -c "CREATE ROLE cost_momentum LOGIN PASSWORD 'cost_momentum';"
sudo -u postgres createdb -O cost_momentum cost_momentum
python3.12 manage.py migrate
```

Пароль в примере необходимо заменить и синхронно указать в `.env`.

## Исправление ошибки `error parsing value for field "symbols"`

Версия 1.1.1 поддерживает в `.env` оба формата списков:

```env
SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT
HORIZONS_HOURS=4,8,12
```

и JSON-массивы:

```env
SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT"]
HORIZONS_HOURS=[4,8,12]
```

В предыдущей версии Pydantic Settings пытался декодировать значения как JSON до запуска пользовательского валидатора. Это исправлено с помощью `NoDecode` и явного разбора обоих форматов.


## Динамический полный universe фьючерсов

Версия 1.2.1 по умолчанию использует `UNIVERSE_MODE=dynamic`. Система больше не ограничена списком BTC/ETH/SOL: она получает весь каталог активных linear-инструментов Bybit с пагинацией, сопоставляет его с общим ticker snapshot и каждый цикл формирует tradable universe.

Базовая конфигурация:

```env
UNIVERSE_MODE=dynamic
UNIVERSE_MIN_AGE_DAYS=7
UNIVERSE_MIN_TURNOVER_24H=2000000
UNIVERSE_MAX_SPREAD_BPS=30
UNIVERSE_MAX_SYMBOLS=0
UNIVERSE_REFRESH_SECONDS=300
UNIVERSE_MIN_HISTORY_BARS=72
```

`UNIVERSE_MAX_SYMBOLS=0` означает анализ всех контрактов, прошедших фильтры. Для эксперимента с фиксированным набором переключите `UNIVERSE_MODE=static`; тогда используется `SYMBOLS`.

Состав и причины исключения отображаются в `/api/v1/status` внутри heartbeat worker и в деталях jobs `market_sync`/`hourly_inference`.

Начиная с 1.2.1, после стартовой загрузки система немедленно выполняет catch-up inference для всего отобранного universe. В верхней строке интерфейса отображается `Universe: N из M · динамический · карточек K`; UI запрашивает до 2000 актуальных рекомендаций, поэтому старые пять демонстрационных карточек больше не маскируют фактический состав.

## Одна текущая рекомендация на символ

Часовой сигнал действует 90 минут по умолчанию, а inference выполняется каждый час. Поэтому без явного замещения две соседние рекомендации одного символа могли одновременно оставаться `PUBLISHED` и отображаться отдельными плитками.

Начиная с версии 1.2.2, перед публикацией нового сигнала worker переводит предыдущую текущую рекомендацию того же символа в `SUPERSEDED`. Незавершенные операторские планы старого сигнала также закрываются как замененные. Принятые, введенные и частично исполненные планы не удаляются и продолжают отображаться в торговом журнале.

После обновления существующей установки обязательно примените миграцию:

```powershell
py -3.12 manage.py migrate
```

Миграция очищает уже накопившиеся дубликаты и создает ограничение PostgreSQL, запрещающее более одного `PUBLISHED`-сигнала на символ.

## Контрфактические исходы

Версия 1.6.0 добавила автоматический post-event журнал, который не зависит от того, принял оператор рекомендацию или нет. Версия 1.7.0 уточняет порядок касаний внутри неоднозначного часового бара. После синхронизации очередной закрытой свечи worker:

1. проверяет непрерывный ряд confirmed `last`-price candles от `event_time` до барьера или конца горизонта;
2. фиксирует исход первичного барьера `TP` / `SL` / `TIMEOUT` в `advisory.signal_outcomes`;
3. при касании TP и SL в одном часовом баре запрашивает только этот точный 1/3/5-минутный `last`-price window и определяет первое касание по непрерывному intrabar path;
4. оставляет outcome pending при неполном intrabar path, а при TP+SL внутри одного самого мелкого бара сохраняет консервативный `SL` и `ambiguous=true`;
5. создает отдельную оценку для каждой версии execution plan в `advisory.plan_outcomes`;
6. показывает результат во вкладке «Экономика» подробного диалога и публикует audit/outbox события.

Оценочный net P&L плана использует сохраненные в plan snapshot комиссии, slippage, stop-gap reserve и только пересеченные funding settlements. Legacy-план без сохраненного funding timeline помечается `FUNDING_UNAVAILABLE` и не получает фиктивный результат в R. Это **не фактический P&L ручной сделки** и не заменяет журнал fills. При отсутствии полной подтвержденной часовой или требуемой intrabar-последовательности система остается fail-closed и не записывает выдуманный исход.

По умолчанию используется `OUTCOME_INTRABAR_INTERVAL=5`; допустимы `1`, `3` и `5`. Параметр `OUTCOME_INTRABAR_MAX_WINDOWS_PER_CYCLE` ограничивает число точечных запросов за один worker cycle.

После обновления с 1.5.0 примените новую миграцию:

```bash
python manage.py migrate
```

При обновлении с 1.6.0 на 1.7.0 новая migration не требуется; при необходимости явно задайте `OUTCOME_INTRABAR_INTERVAL` и лимит windows в `.env`.

При обновлении с 1.7.0 на 1.7.1 migration и новые переменные окружения не требуются. Перезапустите API/worker/trainer после замены файлов. Уже созданные orphan `.joblib`, отсутствующие в `model-registry list`, автоматически не активируются; их можно сохранить для аудита или удалить после появления зарегистрированного кандидата.

При обновлении с 1.7.2 на 1.7.3 migration не требуется. В `.env` рекомендуется добавить `AUTO_TRAIN_RECOVERY_RETRY_MINUTES=15`; при отсутствии переменной применяется это же безопасное значение по умолчанию. Если active artifact удален либо active registry model является deterministic baseline, trainer после `AUTO_TRAIN_INITIAL_DELAY_SECONDS` проверяет достаточность данных и запускает обучение, не ожидая обычного weekly/data-change trigger. Повреждение файла, SHA256 mismatch и несовместимый artifact по-прежнему не считаются восстанавливаемым отсутствием.

При обновлении с 1.7.3 на 1.7.4 migration и новые переменные окружения не требуются. Перезапустите процессы после замены файлов. Если legacy/imported signal содержит инвертированные entry/SL/TP, новый execution plan будет заблокирован как `BLOCKED_INVALID_INPUT`; такие данные следует исправить в источнике, а не обходить проверку. Ручной fill, расположенный уже за stop-границей относительно направления, отклоняется с HTTP 422.

При обновлении с 1.7.4 на 1.7.5 migration и новые переменные окружения не требуются. Перезапустите процессы после замены файлов. Legacy/imported profile, account snapshot или instrument spec с `NaN`, `Infinity`, неположительными обязательными значениями либо отрицательными комиссиями/reserves теперь формирует zero-sized `BLOCKED_INVALID_INPUT` с диагностикой; исправьте источник данных, не обходите блокировку.

При обновлении с 1.7.5 на 1.7.6 примените migration:

```bash
python manage.py migrate
```

Migration `0005_plan_outcome_invalid_input` разрешает новый terminal status `INVALID_INPUT` в `advisory.plan_outcomes`. Поврежденный immutable sizing/cost/funding snapshot получает нулевую оценку и диагностический `validation_error`; другие plan versions продолжают обрабатываться. Новые `.env` переменные не требуются.

При обновлении с 1.7.6 на 1.7.7 migration и новые `.env` переменные не требуются. Перезапустите API/worker/trainer. Если в `models/` уже находится файл, отсутствующий в `model-registry list`, выполните контролируемое восстановление:

```bash
python manage.py model-registry recover-artifact --artifact models/<artifact>.joblib
```

Команда работает только вне production при `ALLOW_BASELINE_MODEL=true`, требует отсутствующую/базовую active-модель, повторно валидирует task/schema/classes/version/horizon и запускает абсолютный ML/policy gate. Artifact, не прошедший gate, регистрируется inactive и не активируется.

При обновлении с 1.7.7 на 1.7.8 migration и новые `.env` переменные не требуются. Перезапустите API/worker/trainer. Новые candidates, которые должны быть активированы сразу, теперь регистрируются, переключают active-row и создают audit/outbox события одной транзакцией; существующие inactive candidates и ручной rollback работают как раньше.

При обновлении с 1.7.8 на 1.7.9 migration и новые `.env` переменные не требуются. Перезапустите API/worker/trainer. Исторические значения `log_loss`, уже сохраненные кандидатами версии 1.7.8 и ниже, автоматически не переписываются; для корректного quality gate требуется новое обучение или повторная оценка artifact кодом 1.7.9. Не повышайте `AUTO_TRAIN_MAX_LOG_LOSS` для обхода старой ошибочной метрики.

## Управление проектом

Все команды кроссплатформенные и выполняются через `manage.py`:

```text
python manage.py setup          создать .venv и установить зависимости
python manage.py configure      сгенерировать SECRET_KEY и задать пароль оператора
python manage.py db-init        создать локальную роль и базу PostgreSQL
python manage.py migrate        применить Alembic migration
python manage.py doctor         проверить Python, PostgreSQL, утилиты и migration head
python manage.py run            запустить API, inference worker и trainer
python manage.py api            запустить только API
python manage.py worker         запустить только inference worker
python manage.py trainer        запустить только background trainer
python manage.py test           запустить тесты
python manage.py lint           выполнить Ruff
python manage.py backup         создать pg_dump в backups/
python manage.py restore-check  восстановить dump во временную базу и проверить данные
python manage.py report         сформировать ежедневный отчет
python manage.py model-registry list                         список моделей
python manage.py model-registry activate --version VERSION   активация или rollback
python manage.py model-registry recover-artifact --artifact PATH   проверка и восстановление orphan artifact
```

На Linux/macOS эти же команды доступны как цели `make`, но `make` не является обязательным.

## PostgreSQL integration tests

`python manage.py test` использует `TEST_DATABASE_URL`, если он задан. Если указан `POSTGRES_ADMIN_URL`, test runner сам создает временную базу, выполняет integration-тесты и удаляет ее. Без обоих параметров запускаются unit-тесты.

Пример PowerShell без постоянного хранения административного пароля в `.env`:

```powershell
$env:POSTGRES_ADMIN_URL="postgresql+psycopg://postgres:ADMIN_PASSWORD@localhost:5432/postgres"
py -3.12 manage.py test --require-integration
Remove-Item Env:POSTGRES_ADMIN_URL
```

## Демонстрационные данные

После входа откройте «Сервис» → «Создать демонстрационные данные». Операция доступна только при `ALLOW_DEMO_SEED=true`.

## Режимы

- `paper`: виртуальный капитал и ручная регистрация сделок.
- `shadow`: реальные рыночные сигналы без исполнения.
- `production`: advisory-only; отправка ордеров не реализована и не разрешена архитектурой клиента.
- `backtest`: исследовательские CLI-процессы с PostgreSQL.

## Автоматическое переобучение и активация

При обычном запуске `python manage.py run` стартует отдельный trainer-процесс. По умолчанию он:

1. после стартовой задержки строит профиль доступного датасета: число свечей, временных точек, символов, глубину и coverage;
2. запускает обучение по недельному расписанию **или раньше**, если появился крупный исторический backfill, существенно изменился состав top-N символов либо действующая модель не содержит dataset profile;
3. создает новый immutable joblib artifact и регистрирует его как неактивный candidate;
4. оценивает candidate и текущую active-модель на одном новом final holdout;
5. проверяет log loss, Brier/ECE, представленность классов и cost-aware policy metrics: число исполнимых сделок, realized mean R, profit factor и drawdown;
6. автоматически и атомарно активирует candidate только после абсолютных и incumbent-relative gates;
7. оставляет не прошедшую проверку модель неактивной, не нарушая текущий inference;
8. если зарегистрированный incumbent физически утрачен, в разрешенном non-production recovery-mode сравнивает новый candidate только с абсолютными gates и атомарно заменяет stale registry entry лишь при успешной проверке.

Это не `partial_fit` существующего файла. Модель безопасно пересобирается на расширенном/скользящем наборе данных, а предыдущие версии остаются доступны для rollback. CPU-нагрузка обучения вынесена из API и inference worker. Оператор не обязан вручную выбирать штатную модель; ручная активация остается только инструментом review и аварийного rollback.

Worker отдельно выполняет progressive history backfill: быстрый стартовый срез загружается сразу, затем история активного universe расширяется назад небольшими пакетами до `HISTORY_BACKFILL_TARGET_DAYS`. Поэтому `AUTO_TRAIN_LOOKBACK_DAYS=365` теперь может реально использовать до года данных, а не только последние 500 уже сохраненных свечей.

Основные параметры находятся в `.env`: `AUTO_TRAIN_ENABLED`, `AUTO_TRAIN_INTERVAL_HOURS`, `AUTO_TRAIN_MIN_NEW_TIMESTAMPS`, dataset-change thresholds, policy gates, `HISTORY_BACKFILL_*`, `AUTO_TRAIN_AUTO_ACTIVATE`. Для штатного paper/shadow режима рекомендуется оставить auto-activation включенной; candidate будет продвинут только при доказанном улучшении на общем holdout.

Ручной контур сохранен:

```bash
python manage.py train --horizon 8 --model-type logistic
python manage.py model-registry list
python manage.py backtest --model models/<artifact>.joblib --output reports/backtest.json
python manage.py model-registry activate --version <model-version>
python manage.py model-registry recover-artifact --artifact models/<artifact>.joblib
python manage.py report --output reports/daily_report.json
python manage.py replay --signal-id <UUID> --output reports/replay.json
```

Trainer и ручное обучение создают direction-specific метки `TP`, `SL`, `TIMEOUT`, используют хронологические train/calibration/final-holdout окна и immutable artifacts. Worker проверяет SHA256, task/schema/classes/horizon и загружает новую active-версию без перезапуска. Активация предыдущей версии является rollback.

Baseline остается только операционной заглушкой для non-production режимов. Его вероятности не калиброваны, каждая рекомендация содержит предупреждение, а heartbeat/UI показывают состояние `DEGRADED`. При отсутствии active registry row или физического файла active artifact worker может использовать baseline только при `ALLOW_BASELINE_MODEL=true`; явный `ACTIVE_MODEL_PATH`, SHA256 mismatch, поврежденный или несовместимый artifact остаются fail-closed. В `production` конфигурация требует `ALLOW_BASELINE_MODEL=false`, безопасные credentials и отключенный demo seed.

Текущий backtest еще не моделирует исторический стакан, partial fills, полноценный портфель и задержки оператора. Поэтому работающий ML pipeline и положительный отчет не являются доказательством прибыльности. Полная матрица соответствия: [SPEC_COMPLIANCE](docs/SPEC_COMPLIANCE.md).

## Безопасность

Bybit-клиент содержит только GET-методы для public/read-only endpoints. В кодовой базе отсутствуют методы создания, изменения или отмены ордеров. Для приватного read-only режима используйте отдельный ключ без права торговли и вывода средств. API слушает `127.0.0.1`; внешний доступ следует публиковать только через аутентифицированный TLS reverse proxy.

Подробности: [нативная установка](docs/NATIVE_INSTALL.md), [конфигурация](docs/CONFIGURATION.md), [руководство оператора](docs/OPERATOR_MANUAL.md), [инциденты](docs/INCIDENT_RUNBOOK.md), [model card](docs/MODEL_CARD.md), [безопасность](docs/SECURITY.md), [отчет QA](docs/QA_REPORT.md).

## Примечание для Windows и psycopg

Версия 1.1.3 запускает FastAPI, worker и остальные асинхронные CLI-команды через явный selector-based event loop на Windows. Это не зависит от выбора loop внутри Uvicorn и совместимо с async psycopg. Дополнительные команды или ручная настройка `asyncio` не требуются.
