# Отчет об итерации 1.7.2 — controlled recovery после удаления model artifacts

Дата: 28 июня 2026 г.  
Входной архив: `cost_aware_momentum-1.7.1-json-safe-model-registry.zip`  
SHA-256 входного архива: `75740b1e1a908e4a7040ee5bbaa6f9d8b2876e253d5e5eaa3d82b3d2c158788b`  
Версия до изменения: `1.7.1`  
Версия после изменения: `1.7.2`

## Цель итерации

После этой итерации система должна продолжать безопасную non-production работу после случайного удаления active `.joblib`: worker запускается на явно обозначенном deterministic baseline, trainer может восстановить полноценную active-модель через штатный candidate lifecycle, а production и ошибки целостности остаются fail-closed.

## Критерии приемки

1. Отсутствующий файл registry-active модели не завершает worker при `ALLOW_BASELINE_MODEL=true` и `APP_MODE != production`.
2. Effective runtime становится `baseline-momentum-v1`, heartbeat — `DEGRADED`, а причина доступна в status/UI.
3. Отсутствие любой active registry row поддерживает bootstrap baseline до первой модели.
4. Production, `ALLOW_BASELINE_MODEL=false` и отсутствующий `ACTIVE_MODEL_PATH` остаются fail-closed.
5. Существующий, но поврежденный или не совпадающий по SHA256 artifact не обходится fallback-механизмом.
6. Trainer не пытается сравнивать candidate с физически отсутствующим incumbent; recovery-кандидат проходит абсолютные ML/policy gates как при bootstrap.
7. Stale active registry row заменяется только штатной atomic activation прошедшего gate кандидата; registry row не удаляется автоматически.
8. Новые migration и environment variables не требуются.

## Baseline до правок

После распаковки архива и установки отсутствовавших в host environment declared tools (`psycopg`, `ruff`) выполнены проверки:

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5; проект требует `>=3.12` |
| `python -m pip check` | FAILED (host environment) | внешний конфликт `moviepy 2.2.1` / `pillow 12.2.0`, не объявленный проектом |
| `python -m compileall -q app scripts tests manage.py` | PASSED | без ошибок |
| `python -m ruff check .` | PASSED | без замечаний |
| `python -m pytest -q` | PASSED | 77 passed, 3 skipped |
| `node --check web/js/app.js` | PASSED | без ошибок |
| `python manage.py doctor` | NOT RUN корректно | command wrapper требует созданную project `.venv`; среда поставки ее не содержит |
| `python manage.py test --require-integration` | NOT RUN | нет project `.venv` и отдельной PostgreSQL test database |

Три skipped tests относятся к PostgreSQL integration. SQLite/fake database вместо PostgreSQL не использовалась.

## Доказательство дефекта

### CONFIRMED DEFECT — worker startup failure

Файл: `app/workers/runner.py`, метод `Worker.refresh_model_runtime()`.

Исходная ветка при наличии active registry row безусловно создавала `ModelRuntime(Path(registry.artifact_path), allow_baseline=False)`. `ModelRuntime.load()` обнаруживал удаленный файл и выбрасывал:

```text
RuntimeError: Active model artifact does not exist: ...\models\<version>.joblib
```

Исключение возникало до первого heartbeat и вне startup `try`, поэтому worker завершался с кодом 1. API и trainer могли оставаться запущенными, но inference прекращался.

Severity: **high operational** для paper/shadow; production loss не маскировался, но non-production recovery отсутствовал.

### CONFIRMED GAP — trainer не мог самовосстановиться

Файлы: `app/workers/trainer.py`, `app/ml/lifecycle.py`.

Trainer передавал stale registry row как incumbent. `build_model_candidate()` не мог загрузить удаленный artifact и записывал `comparison_skipped=incumbent_load_or_evaluation_failed`. `evaluate_quality_gate()` добавлял `incumbent_comparison_unavailable`, поэтому candidate не мог пройти gate и автоматически заменить утраченный incumbent.

### Почему тесты не обнаружили проблему

До версии 1.7.2 проверялись:

- baseline при отсутствии active registry row;
- strict artifact validation;
- production prohibition baseline;
- normal registry activation/reload.

Не было контракта для состояния «active row существует, но его файл удален» и не проверялся фактический `Worker.refresh_model_runtime()` в таком сценарии.

## Red → green

До production implementation добавлен `tests/unit/test_model_runtime_fallback.py`.

RED:

```text
python -m pytest -q tests/unit/test_model_runtime_fallback.py
ModuleNotFoundError: No module named 'app.ml.runtime_selection'
```

После реализации:

```text
python -m pytest -q tests/unit/test_model_runtime_fallback.py
11 passed
```

Тесты покрывают:

- missing active artifact → baseline recovery;
- фактический `Worker.refresh_model_runtime()` с mock PostgreSQL session;
- no-registry bootstrap;
- `ALLOW_BASELINE_MODEL=false`;
- production boundary;
- strict `ACTIVE_MODEL_PATH`;
- SHA256/integrity failure без fallback;
- readiness для controlled degraded state.

## Реализация

### Выбор model runtime

Добавлен `app/ml/runtime_selection.py` с одним каноническим decision flow:

```text
ACTIVE_MODEL_PATH задан
  -> strict override load, без fallback

active registry row отсутствует
  -> bootstrap baseline, только если явно разрешен non-production

active registry row = deterministic_baseline
  -> registry baseline, только если явно разрешен non-production

trained active row, файл отсутствует
  -> controlled baseline recovery, только если явно разрешен non-production

trained active row, файл существует
  -> строгая SHA/version/task/schema/classes/horizon validation
```

Fallback не применяется к существующему, но поврежденному/подмененному/несовместимому artifact.

### Worker и диагностика

Worker хранит `model_notice` и публикует его в heartbeat:

- `NO_ACTIVE_MODEL_REGISTERED`;
- `REGISTRY_BASELINE_ACTIVE`;
- `ACTIVE_MODEL_ARTIFACT_MISSING`.

Baseline runtime работает со статусом `DEGRADED`. Это не скрытая подмена: `ModelRuntime.metadata().source` содержит конкретный источник, UI показывает effective runtime, а market signals сохраняют существующее предупреждение о некалиброванном baseline.

### Readiness

`/health/ready` допускает HTTP-ready состояние при controlled baseline degradation только если одновременно:

- heartbeat свежий;
- market sync свежий;
- worker не содержит другой `error`;
- notice code входит в фиксированный whitelist;
- baseline разрешен конфигурацией;
- notice согласован с registry version.

Ответ сохраняет `degraded=true`, `fallback_active=true`, stale registry version и artifact path. Любая другая DEGRADED-причина остается неготовностью.

### Trainer recovery

Если active artifact физически отсутствует и baseline recovery разрешен:

- unavailable incumbent не передается в same-holdout comparison;
- candidate оценивается как bootstrap по действующим абсолютным ML/policy gates;
- `AUTO_TRAIN_REQUIRE_IMPROVEMENT` не сравнивает candidate с выдуманным incumbent;
- successful candidate активируется с optimistic guard `expected_previous_version` stale registry row;
- failed candidate регистрируется inactive;
- `incumbent_recovery` сохраняется в trainer state/job result, registry metrics и audit payload.

### UI

Верхняя строка теперь использует `active_model.worker_runtime`, а не только registry version:

- зеленый статус для обычной обученной модели;
- желтый статус «Система доступна с ограничениями» для baseline;
- отдельный текст для отсутствующего artifact, bootstrap без registry и явно активного registry baseline.

## Сохраненные инварианты

- Advisory-only: Bybit order methods не добавлены.
- PostgreSQL-only: SQLite/fallback DB не добавлены.
- Production remains fail-closed: validator требует `ALLOW_BASELINE_MODEL=false`.
- Artifact integrity remains fail-closed: SHA256, task, schema, classes, version и horizon не ослаблены.
- Registry row не удаляется и не редактируется автоматически при потере файла.
- Candidate не активируется без quality gate и atomic registry activation.
- API, worker и trainer остаются отдельными процессами.

## Измененные production files

- `app/ml/runtime_selection.py` — новый model runtime decision layer;
- `app/ml/runtime.py` — baseline metadata сохраняет фактический source;
- `app/workers/runner.py` — controlled fallback, notices и DEGRADED heartbeat;
- `app/workers/trainer.py` — bootstrap recovery для missing incumbent;
- `app/ml/lifecycle.py` — recovery context в registry/audit;
- `app/api/v1/status.py` — readiness/status semantics;
- `web/js/app.js`, `web/css/app.css` — effective runtime и yellow degraded state.

Тест: `tests/unit/test_model_runtime_fallback.py`.

Документация: README, CHANGELOG, PATCH 1.7.2, architecture/configuration/model card/security/operator/incident/QA/spec/traceability.

## Post-check

| Команда | Статус | Результат |
|---|---|---|
| `python -m compileall -q app scripts tests manage.py` | PASSED | без ошибок |
| `python -m ruff check .` | PASSED | без замечаний |
| `python -m pytest -q` | PASSED | 88 passed, 3 skipped |
| `python -m pytest -q tests/unit/test_model_runtime_fallback.py` | PASSED | 11 passed |
| `node --check web/js/app.js` | PASSED | без ошибок |
| `alembic heads` | PASSED | `0004_counterfactual_outcomes` |
| `python -m pip check` | FAILED (host environment) | внешний moviepy/pillow conflict, не зависимость проекта |
| PostgreSQL integration | NOT RUN | отдельная test database отсутствует |

## Обновление установленной копии

Migration и изменения `.env` не требуются.

1. Остановить текущий `python manage.py run`.
2. Заменить файлы проекта версией 1.7.2, сохранив пользовательские `.env`, `models`, `reports`, `backups`.
3. Запустить:

```powershell
python manage.py migrate
python manage.py run
```

При уже удаленном active artifact ожидается:

```text
worker status: DEGRADED
effective model: baseline-momentum-v1
model_notice.code: ACTIVE_MODEL_ARTIFACT_MISSING
```

После успешного training/activation worker самостоятельно загрузит новую active model в пределах `MODEL_REFRESH_SECONDS` и вернется к `RUNNING`.

## Commit message

```text
fix(model-runtime): recover safely from missing active artifacts

- fall back to deterministic baseline only in explicitly allowed non-production modes
- keep production, model overrides and artifact integrity failures fail-closed
- expose controlled fallback through worker heartbeat, readiness and UI
- let trainer rebuild a missing incumbent through absolute bootstrap gates
- preserve stale registry state until guarded candidate activation
- record recovery context in jobs, registry metrics and audit events
- add startup, boundary and readiness regression tests
- bump project version to 1.7.2
```
