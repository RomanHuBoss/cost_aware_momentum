# Iteration report — trainer-control crash recovery

Дата: 2026-06-28
Release: 1.8.1

## 1. Входной архив и исходное состояние

- Входной архив: `cost_aware_momentum-main(3).zip`.
- SHA-256: `1ccf729615b186ec039bc8adf3a22b820a443bfe7b3fe40e78d5dc95e635d556`.
- Исходная версия package/application: `1.8.0` / `1.8.0`.
- Python requirement: `>=3.12`; проверка выполнена на Python 3.13.5.
- Alembic migrations: 5; единственный head `0005_plan_outcome_invalid_input`.
- Исходные counts: 78 production/support frontend/Python files, 22 test files, 27 documentation/Markdown files.
- Release-мусор в исходном ZIP не обнаружен: `.env`, `.venv`, caches, `*.pyc`, `*.egg-info`, dumps и реальные model artifacts отсутствовали.
- В архиве отсутствовали заявленные мастер-промптом `CHANGELOG.md` и `PATCH_*.md`; история была представлена `README.md`, `docs/QA_REPORT.md` и `docs/ITERATION_REPORT_*`. В этой итерации создан канонический `CHANGELOG.md` и `PATCH_1.8.1.md`.

## 2. Цель и критерии приемки

Цель:

> После этой итерации аварийно оставленная `RUNNING`-команда trainer не должна бессрочно блокировать очередь; recovery должен быть атомарным, аудируемым и защищенным от позднего completion старого процесса.

Критерии:

1. Request признается stale только при возрасте claim не менее пяти минут и stale/missing heartbeat владельца.
2. Fresh owner heartbeat запрещает recovery.
3. Старая попытка остается terminal `FAILED`; она не возвращается в `PENDING` и не теряет историю.
4. Автоматический retry создается отдельной строкой с `retry_of` и `recovery_count`.
5. Enqueue/claim/recovery сериализуются PostgreSQL advisory lock.
6. Audit и outbox фиксируются в той же транзакции.
7. Late completion старого claim не изменяет terminal/replacement state.
8. Существующие model gates, advisory training lock, API authentication/CSRF и advisory-only boundary не меняются.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `pyproject.toml`, `.env.example`, `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`, последние отчеты 1.8.0/1.7.12/1.7.11/1.7.10 и релевантные части исходной DOCX-спецификации. Спецификация требует durable `job_runs`, `service_heartbeats`, PostgreSQL locks, audit/outbox и отдельный trainer-процесс.

Изменяемый поток:

```text
operator POST /api/v1/admin/trainer-control
→ advisory lock + stale predecessor check
→ ops.job_runs PENDING
→ trainer advisory lock + stale recovery
→ row-lock claim + claim_token + RUNNING
→ scheduler/recovery evaluation
→ guarded completion
→ audit/outbox + status/UI payload
```

## 4. Baseline до правок

Host environment был проверен первым и не использовался как доказательство проекта:

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED (host) | внешний конфликт `moviepy 2.2.1` / `Pillow 12.2.0`, не объявленный проектом |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | Ruff не установлен |
| `python -m pytest -q` | FAILED (environment) | 10 collection errors: отсутствовал `psycopg` |
| `node --check web/js/app.js` | PASSED | exit 0 |

После установки только declared runtime/dev dependencies в отдельное окружение:

| Команда | Статус | Результат |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | **148 passed, 3 skipped, 19 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0005_plan_outcome_invalid_input (head)` |
| `python manage.py doctor` | FAILED (environment) | project-local `.venv`/`.env`, PostgreSQL tools/service не настроены |
| `python manage.py test --require-integration` | NOT RUN/UNAVAILABLE | отдельная PostgreSQL test database отсутствует |

## 5. Подтвержденный defect

**CONFIRMED DEFECT — high operational/data-integrity severity.**

- Файлы: `app/services/trainer_control.py::enqueue_trainer_control`, `app/workers/trainer.py::claim_control_request` и `finish_control_request`.
- Фактический путь: claim менял `PENDING` на `RUNNING`; после crash строка не имела timeout/recovery. Enqueue дедуплицировал `PENDING/RUNNING`, а claim выбирал только `PENDING`.
- Фактическое поведение: один abandoned `RUNNING` request блокировал все последующие команды бессрочно.
- Ожидаемое поведение: dead-owner request должен получить terminal evidence и безопасный retry без ручного SQL.
- Влияние: оператор не мог повторить проверку/recovery; ручное изменение status могло разрушить audit trail или допустить поздний overwrite.
- Почему тесты не поймали: 1.8.0 покрывала enqueue/claim/processing happy paths, heartbeat freshness и gates, но не crash между claim и completion и не ownership fencing completion.

Остальные крупные research gaps — multi-fold walk-forward, drift control, historical orderbook impact и forward evidence — не входили в scope.

## 6. План и фактический diff

Production:

- `app/services/trainer_control.py`: stale policy, shared lock, dead-owner recovery, linked retry, audit/outbox, status payload metadata.
- `app/workers/trainer.py`: recovery-before-claim, unique claim token, guarded completion.
- `app/api/v1/admin.py`: settings передаются в enqueue recovery policy.
- `app/api/v1/status.py`: `stale_after_seconds`, `retry_of`, `recovery_count`.
- `app/__init__.py`, `pyproject.toml`: версия 1.8.1.

Tests:

- новый `tests/unit/test_trainer_control_recovery.py`;
- обновлен `tests/unit/test_trainer_operator_control.py` для claim-token contract;
- расширен `tests/integration_postgres/test_migrations_and_audit.py` реальным transactional recovery test.

Docs/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.8.1.md`;
- `docs/ARCHITECTURE.md`, `docs/OPERATOR_MANUAL.md`, `docs/INCIDENT_RUNBOOK.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- данный iteration report.

Migration, новая dependency и новая `.env` переменная не добавлялись.

## 7. Red → green evidence

До production implementation создан и выполнен:

```bash
python -m pytest -q tests/unit/test_trainer_control_recovery.py
```

RED на версии 1.8.0:

```text
3 failed
```

Причины:

- отсутствовал `trainer_control_request_is_stale`;
- claim не выполнял recovery перед выбором `PENDING`;
- completion не имел claim-token/status fencing.

После реализации тот же regression module расширен проверкой фактического fail-and-requeue flow:

```text
4 passed
```

Тесты используют независимые UTC timestamps и отдельный heartbeat oracle; production output не используется для построения ожидаемого результата.

## 8. Migration, API, configuration и compatibility

- Version type: patch `1.8.0` → `1.8.1`.
- Alembic: без изменений, head `0005_plan_outcome_invalid_input`.
- `.env`: без изменений. Порог вычисляется как `max(300, HEARTBEAT_SECONDS * 4)`.
- API: backward-compatible расширение status payload; существующий POST contract не изменен.
- Existing rows: stale `RUNNING` rows 1.8.0 могут быть автоматически терминализированы после запуска 1.8.1; completed/PENDING rows не переписываются.
- Audit: abandoned attempt и retry имеют разные IDs и отдельные события.
- Rollout: перезапустить API и trainer.

## 9. Post-check

| Команда | Статус | Результат |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | **152 passed, 4 skipped, 19 warnings** |
| trainer-control targeted suite | PASSED | **19 passed, 4 skipped** включая skipped PostgreSQL module |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0005_plan_outcome_invalid_input (head)` |
| version consistency | PASSED | package/application `1.8.1` |
| whitespace/release scans | PASSED | фиксируется повторно после упаковки |

## 10. Не удалось проверить

- Новый PostgreSQL integration test не выполнен: `TEST_DATABASE_URL`/`POSTGRES_ADMIN_URL` и отдельная test database отсутствуют. Он корректно входит в четыре skipped tests.
- Не выполнен multi-process crash/restart smoke на реальном PostgreSQL и Windows service manager.
- Не проверялось поведение при длительном полном outage PostgreSQL; recovery требует доступной БД.
- Не выполнялось обучение на пользовательской истории, paper/shadow forward period или доказательство экономического преимущества.

## 11. Остаточные риски и ограничения

- Пять минут — консервативный floor. До его истечения команда остается `RUNNING`, даже если owner уже погиб.
- Несколько trainer-процессов должны иметь уникальные `TRAINER_ID`; одинаковые IDs ухудшают диагностику heartbeat, хотя training session advisory lock продолжает предотвращать параллельное fitting.
- Если heartbeat stale из-за DB/network pause, а старый процесс затем оживает, его control completion будет отвергнут; фактический model training дополнительно сериализуется существующим session advisory lock.
- Audit/outbox correctness доказана unit-level; фактическая PostgreSQL транзакция ожидает integration run.

## 12. Rollback

1. Остановить API и trainer.
2. Восстановить source tree 1.8.0.
3. Alembic downgrade не требуется.
4. Не удалять `TRAINER_CONTROL_STALE_RECOVERED`/`REQUEUED` audit/outbox rows: 1.8.0 их игнорирует как историю.
5. Проверить, что нет оставшегося `RUNNING` control request; при rollback автоматический stale recovery снова отсутствует.
6. Перезапустить процессы.

Rollback повторно открывает бессрочную блокировку abandoned `RUNNING` request.

## 13. Рекомендуемый следующий work package

Выполнить новый PostgreSQL integration test в выделенной БД и добавить deterministic multi-process crash/restart smoke: один trainer захватывает request и прекращается, второй после heartbeat/age boundary восстанавливает его ровно один раз. Не смешивать эту проверку с ML/drift или strategy changes.
