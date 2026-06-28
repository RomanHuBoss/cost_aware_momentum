# Отчет об итерации 1.7.7 — model artifact reconciliation

## 1. Входной архив и исходная версия

- Входной архив: `cost_aware_momentum-1.7.6-plan-outcome-input-validation.zip`.
- SHA-256: `dc7caaf4bd0f733ad92d7b3426bced5770eefe7dedb96b516b0fb55f8887bd4a`.
- Исходная версия: `1.7.6`.
- Исходный Alembic head: `0005_plan_outcome_invalid_input`.
- В release-архиве отсутствовали `.env`, `.venv`, caches и реальные model artifacts.

## 2. Цель и критерии приемки

После этой итерации система должна различать stale active registry row, inactive registered candidate и unregistered `.joblib`, а оператор должен иметь безопасный способ восстановить orphan artifact без прямого SQL и без обхода quality gate.

Критерии:

1. UI показывает, что новый файл не зарегистрирован, либо показывает stored gate status зарегистрированного candidate.
2. Generic `WAITING` не маскирует recovery backoff или quality-gate cooldown.
3. Recovery принимает только файл внутри `MODEL_DIR` и только в non-production при разрешенном baseline.
4. Artifact повторно проверяется по task, features/classes, filename/version и horizon.
5. Перед регистрацией unregistered artifact повторно проходит абсолютный ML/policy quality gate.
6. Failed-gate candidate остается inactive.
7. Passing artifact активируется только через существующий guarded registry activation с expected previous version.
8. Нормальный trainer lifecycle, production fail-closed и advisory-only boundary не меняются.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `PATCH_1.7.3.md`–`PATCH_1.7.6.md`, `pyproject.toml`, `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`, а также релевантные modules/tests.

Проверенный поток:

```text
trainer/build_model_candidate
→ immutable models/*.joblib
→ register_model_candidate / model.model_registry
→ activate_registered_model
→ worker select_model_runtime
→ heartbeat + /api/v1/status
→ web/js/app.js
```

## 4. Baseline до правок

### Host environment

| Команда | Результат |
|---|---|
| `python --version` | Python 3.13.5 |
| `python -m pip check` | FAILED (environment): внешний конфликт MoviePy/Pillow |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | UNAVAILABLE: Ruff отсутствовал |
| `python -m pytest -q` | FAILED (environment): 6 collection errors, отсутствовал `psycopg` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |

### Isolated project environment from `.[dev]`

| Команда | Результат |
|---|---|
| `python -m pip check` | PASSED |
| `python -m pytest -q` | PASSED — 120 passed, 3 skipped, 20 warnings |
| `python -m ruff check .` | PASSED |

`python manage.py test --require-integration` не запускался: отсутствовала отдельная test database. Post-check `python -m scripts.doctor` выполнен и ожидаемо завершился FAILED с 6 environment errors: отсутствуют `.env`, безопасные secrets, `psql`/`pg_dump`/`pg_restore` и работающий PostgreSQL.

## 5. Подтвержденные defects/gaps

### CONFIRMED GAP — наличие файла не диагностируется как отдельное состояние

- `app/api/v1/status.py` возвращал только active registry row и worker runtime.
- `web/js/app.js` при `ACTIVE_MODEL_ARTIFACT_MISSING` показывал только старую registry version.
- Новый `.joblib` мог быть inactive candidate или orphan, но оператор видел одинаковое сообщение.
- Severity: medium operational/UX.

### CONFIRMED GAP — orphan artifact не имел безопасного recovery workflow

- `scripts/model_registry.py` поддерживал только `list` и `activate` уже зарегистрированной version.
- Прямое добавление registry row/active flag запрещено audit/integrity contract.
- Повторное обучение было единственным штатным путем, даже если доверенный artifact уже создан до сбоя registry insertion.
- Severity: medium operational.

### CONFIRMED GAP — trainer WAITING скрывает причину

- UI отображал любую фазу `WAITING` как «ожидание новых данных».
- `training_cooldown_not_elapsed`, `training_recovery_backoff_not_elapsed` и failed gate уже были в heartbeat, но не выводились.
- Severity: low/medium UX, особенно при baseline recovery.

## 6. План и фактический diff

### Production

- `app/ml/artifact_recovery.py` — строгая реконструкция `ModelCandidate` из доверенного artifact.
- `scripts/model_registry.py` — subcommand `recover-artifact`.
- `app/api/v1/status.py` — latest inactive candidate и orphan inventory.
- `web/js/app.js` — точная диагностика candidate/orphan/gate/cooldown.
- `app/__init__.py`, `pyproject.toml` — версия 1.7.7.

### Tests

- `tests/unit/test_model_artifact_recovery.py` — artifact metadata, gate, recovery flow.
- `tests/unit/test_model_runtime_fallback.py` — candidate/orphan diagnostics.

### Docs

- `README.md`, `CHANGELOG.md`, `PATCH_1.7.7.md`.
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`.
- `docs/CONFIGURATION.md`, `docs/MODEL_CARD.md`, `docs/SECURITY.md`.
- `docs/OPERATOR_MANUAL.md`, `docs/INCIDENT_RUNBOOK.md`.

Migration и `.env` не изменялись.

## 7. Red → green evidence

RED на исходном production code после добавления acceptance tests:

```text
ModuleNotFoundError: No module named 'app.ml.artifact_recovery'
1 error during collection
```

Команда:

```bash
python -m pytest -q tests/unit/test_model_artifact_recovery.py tests/unit/test_model_runtime_fallback.py
```

GREEN после реализации:

```text
17 passed
```

Проверены:

- восстановление metadata и passing absolute gate;
- filename/version mismatch;
- horizon mismatch;
- passing orphan registration/activation flow;
- запрет активации stored failed-gate candidate;
- различение registered artifact и orphan filename.

## 8. Compatibility, DB и API

- Версия: patch `1.7.7`.
- Alembic migration не требуется; head остается `0005_plan_outcome_invalid_input`.
- Новых `.env` переменных нет.
- `/api/v1/status.active_model` получает обратно совместимые дополнительные поля `latest_candidate` и `orphan_artifacts`.
- Existing active model selection не меняется.
- Recovery CLI доступен только при `APP_MODE != production`, `ALLOW_BASELINE_MODEL=true`, отсутствии usable trained active artifact и расположении файла внутри `MODEL_DIR`.
- Joblib загружается только по явной команде оператора; файл неизвестного происхождения использовать запрещено.

## 9. Post-check

| Команда | Результат |
|---|---|
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 126 passed, 3 skipped, 20 warnings |
| targeted recovery/diagnostics | PASSED — 17 passed |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |
| `python -m scripts.model_registry --help` | PASSED — содержит `recover-artifact` |
| `python -m scripts.doctor` | FAILED (environment) — 6 ошибок: `.env`, secrets, PostgreSQL tools/service |

Ранее зеленые тесты не регрессировали. Bybit order mutation methods/endpoints не добавлены.

## 10. Непроверенное

- Реальная команда recovery не выполнялась против пользовательской PostgreSQL и файла `barrier-logistic-h8-20260628T072708Z.joblib`, потому что они не были приложены.
- PostgreSQL integration tests не запускались: отсутствовала отдельная test database.
- Browser smoke-test не выполнялся; frontend проверен синтаксически и backend contract покрыт unit tests.
- `doctor` выполнен, но environment readiness не подтверждена: отсутствуют штатная `.env`, PostgreSQL service/tools.

## 11. Остаточные риски

- Artifact может не пройти текущие absolute gates; в таком случае baseline сохранится намеренно.
- Если файл уже зарегистрирован с failed gate, recovery command не обходит stored decision.
- Joblib/pickle нельзя загружать из недоверенного источника.
- Recovery не доказывает прибыльность модели и не заменяет paper/shadow evidence.

## 12. Rollback

1. Остановить процессы.
2. Вернуть source release 1.7.6.
3. Migration downgrade не требуется.
4. Если 1.7.7 успела зарегистрировать candidate, оставить registry/audit row для истории; при необходимости активировать предыдущую доступную проверенную model через штатный `model-registry activate`.
5. Перезапустить API/worker/trainer и проверить runtime/status.

## 13. Следующий рекомендуемый work package

Сделать activation registration и active switch одной транзакционной service-operation либо добавить автоматическое resume только для уже зарегистрированного `activation_requested=true`, gate-passed candidate после transient failure между registration и activation.
