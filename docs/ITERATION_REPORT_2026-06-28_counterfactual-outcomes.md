# Iteration report — counterfactual outcomes

Дата: 2026-06-28  
Новая версия: 1.6.0

## 1. Входной архив, SHA-256 и исходная версия

- Архив: `cost_aware_momentum-main(3).zip`
- SHA-256: `e65be5d427d869559f22fe46eb7d2ffd9bb387dd7c629119131188b56ea097dc`
- Исходная версия package/app: `1.5.0`
- Python requirement: `>=3.12`
- Исходный Alembic head: `0003_single_active_model`
- Исходные migrations: `0001`, `0002`, `0003`
- Baseline inventory без cache/build metadata: 115 файлов, 67 production Python files, 12 test files, 20 Markdown docs/release notes.
- В исходном ZIP обнаружены release artifacts `cost_aware_momentum.egg-info` и stale `SHA256SUMS`; они исключены из новой поставки.

## 2. Цель итерации и критерии приемки

Цель: после этой итерации система должна автоматически сохранять независимый от решения оператора первичный TP1/SL/TIMEOUT outcome каждого market signal и отдельный post-event estimate каждой execution-plan version, что подтверждается regression tests, миграцией, API/UI и audit/outbox flow.

Критерии:

1. LONG/SHORT barrier geometry соответствует signal contract.
2. Используются только confirmed contiguous hourly candles; missing data остается pending.
3. Same-bar TP/SL разрешается консервативно и явно маркируется.
4. Signal outcome и plan-version outcomes immutable/idempotent.
5. Unsized и legacy funding cases не получают фиктивный R.
6. Результат доступен через detail API/UI и создает audit/outbox events.
7. Добавлена обратно совместимая Alembic migration с downgrade.
8. Полный доступный static/unit suite остается зеленым.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `PATCH_1.2.2.md`–`PATCH_1.5.0.md`, `pyproject.toml`, `.env.example`, обязательные документы `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`, релевантные ORM/API/worker/risk/ML modules и tests, а также приложенная DOCX-спецификация.

Измененный flow:

```text
confirmed hourly Candle rows
        +
MarketSignal(direction, event_time, horizon, entry, TP1, SL)
        |
        v
barrier evaluator -> SignalOutcome
        |
        +-> each ExecutionPlan immutable sizing/cost snapshot
        |                  |
        |                  v
        +-------------> PlanOutcome
                           |
                           v
                 detail API -> UI economics tab
                           |
                           +-> audit chain + transactional outbox
```

Market signal и execution plan остаются раздельными. Новый flow не размещает и не изменяет Bybit orders.

## 4. Baseline

Команды запускались до изменения production code в изолированном venv:

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 54 passed, 2 skipped, 20 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | NOT RUN | wrapper требовал отсутствующую project-local `.venv`; PostgreSQL tools/config также отсутствовали |
| `python manage.py test --require-integration` | NOT RUN | нет project-local `.venv` и отдельной PostgreSQL test database |

## 5. Подтвержденные gaps/risks

### CONFIRMED GAP — automatic post-event outcome отсутствовал

- Severity: medium (research/audit correctness и selection bias).
- Доказательство: `docs/SPEC_COMPLIANCE.md` 1.5.0 прямо относил counterfactual outcome к частичному соответствию; в ORM не было outcome tables, worker не имел resolver job, detail API/UI не возвращали post-event результат.
- Ожидание спецификации: outcome исходного signal и каждой plan version независимо от решения оператора.
- Фактическое поведение: сохранялся signal и operator decision, но TP/SL/TIMEOUT требовал ручной реконструкции.
- Почему tests не ловили: соответствующего сервиса/контракта и acceptance tests не существовало.

### CONFIRMED RISK — unverifiable funding для legacy plan snapshot

- Severity: medium (ошибка post-event net P&L при наивной реализации).
- Доказательство: version 1.5 plan snapshot хранил только cumulative horizon funding rate, без next-settlement и interval. При раннем TP/SL нельзя доказать, что settlement был пересечен.
- Решение: новые plans сохраняют timeline; legacy plans получают `FUNDING_UNAVAILABLE`, funding не выдумывается, counterfactual R остается `null`.

### DOCUMENTED LIMITATION — hourly ambiguity

- Hourly high/low не определяют порядок касаний TP/SL.
- Решение текущего scope: same-bar считается SL и сохраняет `ambiguous=true`; 1–5-minute reconstruction остается следующим этапом.

## 6. План и фактический diff

Production:

- `app/services/outcomes.py` — barrier evaluator, plan valuation, transactional resolver.
- `app/services/execution.py` — immutable funding timeline в новых plan snapshots.
- `app/db/models.py` — `SignalOutcome`, `PlanOutcome`, constraints/indexes.
- `app/workers/runner.py` — startup/hourly outcome job.
- `app/api/serializers.py` — outcome payload.
- `app/api/v1/recommendations.py` — detail API lookup.
- `web/js/app.js` — economics tab и SSE refresh.
- `app/__init__.py`, `pyproject.toml` — версия 1.6.0.

Migration:

- `migrations/versions/0004_counterfactual_outcomes.py`.

Tests:

- `tests/unit/test_counterfactual_outcomes.py`.
- `tests/unit/test_native_management.py`.
- `tests/integration_postgres/test_migrations_and_audit.py`.

Docs/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.6.0.md`.
- `docs/ARCHITECTURE.md`, `OPERATOR_MANUAL.md`, `MODEL_CARD.md`.
- `docs/QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`.
- этот iteration report.

## 7. Red → green evidence

Acceptance module был создан до production implementation.

RED:

```text
python -m pytest -q tests/unit/test_counterfactual_outcomes.py
ERROR collecting tests/unit/test_counterfactual_outcomes.py
ModuleNotFoundError: No module named 'app.services.outcomes'
```

GREEN после implementation:

```text
python -m pytest -q tests/unit/test_counterfactual_outcomes.py
12 passed
```

Тесты используют вручную заданные Decimal outcomes и не используют production evaluator как oracle.

## 8. Migration, API/config/env compatibility

- New head: `0004_counterfactual_outcomes`.
- Upgrade добавляет две таблицы; released migrations 0001–0003 не переписаны.
- Migration использует `IF NOT EXISTS`, поскольку current 0001 на clean install создает current metadata; это сохраняет clean-install и upgrade path без изменения выпущенной migration.
- Downgrade удаляет outcome tables в безопасном FK-порядке.
- Detail API расширен новым nullable field `counterfactual_outcome`; существующие поля не удалены и не переименованы.
- Новых `.env` variables нет.
- `sizing_snapshot.costs` расширен JSONB keys; старые rows читаются обратно совместимо и явно маркируются как funding-incomplete.

## 9. Post-check

Финальные результаты заносятся после release packaging; обязательный доступный suite включает:

```text
python -m pip check
python -m compileall -q app scripts tests manage.py
python -m ruff check .
python -m pytest -q
node --check web/js/app.js
alembic heads
git diff --check
```

На момент code-complete pre-release check: 67 passed, 3 skipped, 20 warnings; isolated outcome module: 12 passed; ruff/node/Alembic/diff checks passed. Итоговый recheck после повторной распаковки указан в разделе 14 ниже.

## 10. Непроверенное

- Реальный PostgreSQL clean install, 0003→0004 upgrade и downgrade: server/tools/test database отсутствовали. `python manage.py test --require-integration` завершился как UNAVAILABLE, поскольку не заданы `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL`.
- `python manage.py doctor` был выполнен через временно подключенный isolated venv и завершился FAILED: отсутствуют `.env`, замененные secrets, `psql`/`pg_dump`/`pg_restore` и PostgreSQL service.
- Long-running worker/API smoke с Bybit public data.
- Concurrent transaction behavior на реальном PostgreSQL, хотя uniqueness + xact advisory lock реализованы и integration assertions обновлены.
- Экономическая корректность на forward data; она не следует из unit tests.

## 11. Остаточные риски и ограничения

- Primary TP1 only; TP2/partial exits/trailing stop не моделируются.
- Hourly ambiguity остается грубой; conservative SL может занижать performance.
- Hypothetical entry равен signal entry reference; entry-zone/no-fill и operator latency не моделируются.
- Funding использует snapshot scenario, а не восстановленный фактический historical rate.
- Batch resolver ограничен и может потребовать несколько hourly cycles при большом backlog.
- Counterfactual outcomes пока не подключены к live realized-performance rollback gate.

## 12. Rollback procedure

1. Остановить процессы.
2. Сделать backup PostgreSQL.
3. Предпочтительно откатить только code и оставить schema 0004: старые версии игнорируют новые tables.
4. Для полного schema rollback на disposable/подтвержденной базе выполнить Alembic downgrade до `0003_single_active_model`; это удалит outcome history.
5. Вернуть package/app 1.5.0, выполнить doctor/integration checks и запустить worker.

## 13. Рекомендуемый следующий work package

Добавить 1–5-minute path reconstruction для ambiguous hourly bars и сравнить conservative hourly labels с intrabar-resolved labels на отдельном temporal OOS protocol. Не совмещать это с portfolio simulator или live rollback в одной итерации.

## 14. Release recheck

Release target: `cost_aware_momentum-1.6.0-counterfactual-outcomes.zip` с одним корневым каталогом `cost_aware_momentum-1.6.0-counterfactual-outcomes/`.

Source-tree post-check перед упаковкой: 67 passed, 3 skipped, 20 warnings; isolated outcome module 12 passed; pip/compileall/ruff/node/Alembic head/diff checks PASSED. `.git`, virtual environments, `.env`, caches, `*.pyc`, `*.egg-info`, build artifacts, model artifacts и stale `SHA256SUMS` исключаются.

Финальный SHA-256 ZIP и результат `unzip -t`/повторной распаковки приводятся в сообщении поставки и sidecar `.sha256`. Встроить SHA-256 самого ZIP внутрь содержащегося в нем отчета невозможно без изменения хеша архива.
