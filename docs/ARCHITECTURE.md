# Архитектура

## Потоки

```text
Bybit public REST/WebSocket/read-only GET
        |
        v
market-data worker -> PostgreSQL market/reference
        |                         |
        |                         v
        |               background trainer -> immutable candidate -> quality gate
        |                                      |                         |
        |                                      v                         v
        |                              PostgreSQL model registry <- safe activation
        v
hourly feature snapshot -> ModelRuntime -> LONG + SHORT outcome scenarios
        |
        v
current bid/ask + cost/risk/policy -> MarketSignal
        |
        v
CapitalProfile + account/portfolio snapshot
        |
        v
ExecutionPlan(versioned) -> FastAPI -> Vanilla JS UI
        |
        v
operator accept/reject -> manual fill journal -> P&L/audit/reconciliation

confirmed hourly candles + MarketSignal
        |
        +-- same-hour TP/SL --> exact 1/3/5m read-only kline window
        |                              |
        v                              v
SignalOutcome -> PlanOutcome(each version) -> API/UI/audit/outbox
```

Market signal не зависит от профиля капитала. Execution plan зависит от профиля и snapshot счета. Один signal имеет несколько versioned plans. При operator accept текущая исполнимая цена определяется как ask для LONG и bid для SHORT; read-only account snapshot проходит отдельную проверку возраста.

Начиная с 1.7.12 manual-close выполняется под row lock сделки и до любой mutation читает последний сохраненный `fills.fill_time`. Новый partial/full fill допускается только при `fill_time >= entry_time` и `fill_time >= latest_fill_time`; одинаковые timestamps разрешены для нескольких биржевых fills.

Начиная с 1.8.10 acceptance использует point-in-time ticker/spec и при adverse executable ask/bid не переносит старый sizing: создается новая plan version с фактическим planning entry, повторным расчетом stress loss, qty, margin, liquidation, net R/R и EV. После ручного fill сделка хранит `initial_stress_loss` и `remaining_stress_loss`; partial close освобождает риск пропорционально оставшемуся qty. Aggregate open risk складывает reservations еще не исполненных accepted plans и remaining risk фактических manual positions, не двойной счет одного состояния.

Counterfactual `PlanOutcome` привязан к immutable snapshot конкретной plan version. Если plan был пересчитан из-за цены/профиля, valuation использует сохраненные `entry_price` и `planning_time` этой версии для P&L и funding settlements; signal-level values остаются только legacy fallback.

## Нативные процессы

- `api`: HTTP/SSE, UI, validation и operator actions; запускается через `python manage.py api`.
- `worker`: ingestion, heartbeats, hourly inference, expiry и counterfactual outcome resolution с точечным intrabar backfill; запускается через `python manage.py worker`.
- `trainer`: периодическое переобучение, same-holdout comparison, quality gate, безопасная activation и обработка операторских `CHECK_NOW`/`RECOVER_NOW`; запускается через `python manage.py trainer`.
- `migrate`: Alembic до первого запуска и после обновлений.
- `train/backtest`: ручные исследовательские CLI-процессы, не request-bound background tasks.
- PostgreSQL: отдельная системная служба и единый state store.

`python manage.py run` является локальным supervisor: запускает API, inference worker и, если `AUTO_TRAIN_ENABLED=true`, trainer как дочерние процессы, контролирует их завершение и останавливает все по `Ctrl+C`. Для постоянной эксплуатации процессы следует зарегистрировать как независимые службы ОС.

В версии 1.8.0 API не запускает fitting внутри HTTP request. Authenticated/CSRF-protected endpoint только создает дедуплицированную запись `trainer_control_request` в `ops.job_runs`, audit и outbox. Отдельный trainer опрашивает очередь каждые две секунды, забирает запись под row lock и выполняет обычный scheduler либо recovery evaluation. `RECOVER_NOW` разрешает пропустить только scheduler cooldown текущего recovery episode; все dataset и model-lifecycle gates сохраняются.

Начиная с 1.8.1 enqueue и claim сериализуются одним PostgreSQL advisory lock. Если `RUNNING`-команда старше пяти минут и heartbeat владельца отсутствует либо stale, прежняя строка остается терминальным `FAILED`-свидетельством, а trainer создает новую `PENDING`-строку с `retry_of` и `recovery_count`. События `TRAINER_CONTROL_STALE_RECOVERED` и `TRAINER_CONTROL_REQUEUED` записываются в audit/outbox в той же транзакции. Каждый claim получает случайный token; завершение принимается только пока строка остается `RUNNING` и token совпадает, поэтому оживший старый процесс не может перезаписать результат восстановления.

Начиная с 1.8.10 artifact/runtime contract требует exact feature schema version, positive integer horizon, non-empty calibration version, ожидаемый class order и полный finite feature vector без silent zero-imputation. Class distribution и incumbent comparison metrics проверяются до promotion fail-closed.

Trainer не модифицирует active artifact. Каждый цикл создает новую immutable-версию, сравнивает ее с incumbent на одном final holdout, сохраняет решение в `model_registry`, `job_runs`, audit и outbox. Начиная с 1.8.9 каждая research observation существует только как полная пара LONG/SHORT для одного `decision_time/symbol`; dataset исключает cohort атомарно, а split, holdout и backtest повторно проверяют cardinality fail-closed. Начиная с 1.8.8 stateful feature calculations ограничены непрерывным сегментом валидных hourly bars, а runtime/training/backtest применяют единый fail-closed TP/SL/TIMEOUT probability-simplex contract. Holdout policy realizes P&L и drawdown в modeled exit time, поэтому overlapping decisions не получают информацию о будущем в момент входа. Начиная с 1.7.11 feature row допускается только при 24 последовательных одночасовых переходах, а label — только при наличии ровно следующих N часовых свечей; затронутые gaps/duplicates исключаются с diagnostics `hourly_continuity`. Начиная с 1.7.10 каждая barrier-label строка содержит фактический `label_end_time`; train и calibration допускаются только когда весь будущий label-window заканчивается до следующего окна, поэтому пропуски часовых свечей не сокращают purge. Номинальный horizon-hour embargo после границы сохраняется отдельно. Classification metrics используют зафиксированный artifact-порядок outcome classes; начиная с 1.7.9 `log_loss` вычисляется прямым выбором вероятности истинного класса и не зависит от внутренней сортировки labels библиотекой. Начиная с 1.7.8 новый gate-passed candidate регистрируется и активируется одной PostgreSQL-транзакцией: active-row блокируется, проверяется expected previous version, а candidate/activation audit и outbox фиксируются вместе. Автоматическая activation использует optimistic guard по предыдущей active-version, поэтому конкурентное изменение registry не может быть незаметно перезаписано. Если incumbent artifact физически утрачен и non-production baseline recovery явно разрешен, сравнение с недоступным файлом не имитируется: candidate проходит только абсолютные gates как при bootstrap и может заменить stale active row лишь после успешной проверки.

## Схемы PostgreSQL

- `reference`: инструменты и point-in-time contract specs.
- `market`: confirmed/unconfirmed candles, tickers, funding, OI.
- `research`: backtest runs и артефакты экспериментов.
- `model`: model registry, hashes и active version.
- `advisory`: profiles, signals, plans, signal/plan outcomes, decisions, fills и positions.
- `audit`: append-only chain и data-quality issues.
- `ops`: job runs, heartbeats, idempotency и outbox.

## Надежность

- natural unique keys и upsert ingestion;
- transaction-scoped advisory locks для коротких jobs и session advisory lock для длительного обучения;
- fail-closed recovery operator-control queue: stale owner определяется одновременно по возрасту claim и heartbeat, брошенная попытка не переиспользуется как будто она не выполнялась, а late completion отвергается по status/claim-token;
- idempotency keys для operator mutations;
- accept-риск сериализуется глобальным transaction-scoped advisory lock: open risk и свежий effective capital читаются после захвата lock, а решение фиксируется до его освобождения при commit/rollback;
- transactional outbox для SSE/catch-up;
- Alembic head check до readiness;
- audit chain с сериализацией chain-head через PostgreSQL advisory lock;
- fail-closed при stale/missing/non-contiguous market data, migration mismatch и невалидном model artifact; физически отсутствующий active artifact имеет отдельный controlled baseline recovery только в non-production при явном разрешении; counterfactual signal outcome не создается при разрыве hourly path или неполном обязательном intrabar window; поврежденный execution-plan snapshot терминально сохраняется как zero-valued `INVALID_INPUT` и изолируется от других plan versions;
- нативные `pg_dump`/`pg_restore` для резервирования и проверки восстановления.

## Security boundary

`BybitClient` предоставляет только public/read-only GET. Даже `ACCEPTED` означает решение оператора, а не биржевой ордер. Фактическое исполнение заносится через manual-entry/manual-close.
