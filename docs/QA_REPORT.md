# QA Report — 1.9.0

Дата: 2026-07-02

## Входной архив

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `9104ab43d0636d8b3aa31cfd7370aeed23009d73b0aa3b604d8ef03fa8b2635b`.
- Исходная версия: `1.8.36`; Python requirement: `>=3.12`.
- Исходный состав: 70 production/maintenance Python files (включая `manage.py`), 50 `test_*.py` modules, 18 Markdown documentation files.
- Alembic revisions: `0001`–`0008`; один head `0008_outcome_path_unavailable`.
- Входной archive не содержал secrets, `.env`, virtualenv, dumps или реальные model artifacts. Baseline-команды создали локальные cache/egg-info только во внешнем рабочем каталоге; они исключены из release.
- Заявления о десятках ошибок не сопровождались путями, stack traces или reproductions. Severity ниже основана только на воспроизводимых доказательствах.

## Baseline до правок

Системный Python не являлся пригодным project environment: `ruff` и `psycopg` отсутствовали, `pip check` сообщал о внешнем конфликте `moviepy/Pillow`, а pytest остановился на 23 import errors. Это зафиксировано как environment failure, не как defect проекта.

Повторный baseline выполнен в чистом внешнем virtualenv с `pip install -e '.[dev]'`:

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **425 passed, 4 skipped, 19 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head: `0008_outcome_path_unavailable` |
| `python manage.py doctor` | NOT RUN | no operator `.env` and no safe project PostgreSQL configured |
| `python manage.py test --require-integration` | NOT RUN | no isolated PostgreSQL test database configured; production/user DB was not used |

## Подтверждённый дефект и исправление

### HIGH — fixed TIMEOUT return distorted EV and direction selection

Production paths:

- `app/ml/training.py::evaluate_policy_model`;
- `scripts/backtest.py::policy_backtest`;
- `app/ml/runtime.py::ModelRuntime._predict_artifact_scenarios`;
- `app/services/signals.py::select_cost_aware_scenario` and signal publication;
- `app/services/execution.py::create_execution_plan` and `validate_execution_plan_for_acceptance`.

До 1.9.0 все TIMEOUT outcomes получали одну gross-return гипотезу `TIMEOUT_GROSS_RETURN_RATE=-0.002`, хотя dataset уже содержал фактический `realized_gross_return` и текущую stop geometry. Положительные и отрицательные TIMEOUT paths, а также LONG/SHORT asymmetry, сводились к одному числу. Это могло:

1. блокировать сценарий с положительным conditional TIMEOUT outcome;
2. одобрять сценарий, где фактический conditional TIMEOUT loss тяжелее −0.2%;
3. выбирать неверное направление при одинаковых TP/SL probabilities;
4. давать разные economics при публикации signal и последующем plan/acceptance после изменения `.env`;
5. искажать promotion/backtest evidence тем же fixed assumption.

Исправление:

- на train window вычисляется `realized_gross_return / barrier_downside_rate` только для TIMEOUT rows;
- отдельно для LONG и SHORT сохраняется медиана (минимум 5 TIMEOUT rows на направление);
- calibration и final holdout не участвуют в fit estimator;
- runtime переносит estimate в каждый directional `Prediction`;
- policy/backtest ограничивают estimate текущей TP/SL support и масштабируют к фактической tick-aligned stop distance;
- market signal сохраняет использованную gross-return величину и source;
- plan и acceptance повторно используют immutable signal snapshot и fail closed на невалидном значении;
- artifact contract получил `timeout_return_schema_version=training-direction-median-r-v1`;
- policy evidence schema повышена до `decision-open-entry-exit-time-cohort-v10`.

## Red → green

Команда до production change:

```text
python -m pytest -q tests/unit/test_conditional_timeout_economics_2026_07_02.py
```

RED: collection error — `TIMEOUT_RETURN_SCHEMA_VERSION` отсутствовал; требуемого artifact/model contract не существовало.

После изменения:

```text
7 passed, 36 warnings
```

Проверяются:

- train-only direction medians and sample counts;
- scenario-specific live direction selection;
- rejection of artifacts without new schema;
- runtime propagation to LONG/SHORT predictions;
- model-aware promotion policy direction selection;
- immutable signal-to-execution TIMEOUT assumption and fail-closed invalid snapshot;
- research backtest use of artifact estimator unless explicit CLI override is supplied.

## Post-check

| Проверка | Статус | Результат |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **432 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head: `0008_outcome_path_unavailable` |
| `python manage.py doctor` | NOT RUN | no operator `.env` and no safe project PostgreSQL configured |
| `python manage.py test --require-integration` | NOT RUN | no isolated PostgreSQL test database configured |

Warnings are third-party NumPy/joblib deprecations emitted by artifact serialization tests; no project test warnings were converted into failures.

## Migration / configuration compatibility

- Database migration: none.
- New `.env` variables: none.
- `TIMEOUT_GROSS_RETURN_RATE` remains valid but is now baseline/legacy fallback only.
- Old 1.8.x artifacts are intentionally incompatible and must be retrained; manual schema editing is prohibited.
- Existing database signals retain their persisted fixed assumption and remain serializable; new plans use that persisted value rather than silently applying the new estimator retroactively.

## Confirmed residual risk outside this iteration

**HIGH / NOT FIXED:** `app/services/market_data.py::_candle_values` sets `available_at=close_time`, while `now` is the actual post-response receipt timestamp. Late history/backfill can therefore appear available at candle close during point-in-time replay. Existing test `test_candle_confirmation_uses_api_response_time` correctly checks confirmation against response time but incorrectly asserts `available_at==close_time`. Correcting this safely requires a separate data-correction migration/reingestion policy because historical receipt timestamps cannot be reconstructed exactly.

Other documented limitations remain: no full historical order book/fills/funding replay, no complete rolling walk-forward/PBO/DSR governance, and current-symbol historical universe selection can retain survivorship/listing bias. Technical correctness does not establish profitability.
