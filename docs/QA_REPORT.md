# QA Report — 1.8.32

Дата: 2026-07-02

## Входной архив и исходное состояние

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `bcf7787004b257a1dcaf17a792f1291733b6246f0d8fd8b4259d3ff1cd1c4854`.
- Исходная версия: `1.8.31`; Python requirement: `>=3.12`.
- Архив не содержал заявленные в собственном QA release-файлы `CHANGELOG.md`, `PATCH_1.8.31.md` и `SHA256SUMS`.
- Alembic содержал две дочерние revision от `0007_position_account_scope`: `0008_outcome_path_unavailable` и `0008_plan_outcome_path_unavailable`. Вторая имела 34-символьный ID и дублировала DDL/backfill первой.

## Baseline до production-правок

### Глобальное окружение

| Проверка | Статус и результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | FAILED — посторонний конфликт MoviePy/Pillow в глобальном окружении |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | UNAVAILABLE — Ruff не был установлен глобально |
| `python -m pytest -q` | FAILED на collection — 22 errors из-за отсутствующего `psycopg` |
| `node --check web/js/app.js` | PASSED |

Глобальные ошибки не использовались как доказательство дефектов проекта. Для воспроизводимого baseline создан отдельный venv и установлен проект `-e .[dev]` без изменения исходников.

### Изолированный venv

| Проверка | Статус и результат |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py migrations` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | FAILED — 1 failed, 407 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | FAILED CONTRACT — два head: `0008_outcome_path_unavailable`, `0008_plan_outcome_path_unavailable` |
| `python manage.py doctor` | NOT RUN — рабочая `.env`/PostgreSQL-конфигурация отсутствовала |
| `python manage.py test --require-integration` | NOT RUN — безопасная отдельная PostgreSQL test database отсутствовала |

Единственный pytest failure: `test_all_alembic_revision_ids_fit_version_table_contract`, фактический oversized ID — `0008_plan_outcome_path_unavailable` длиной 34.

## Подтверждённые дефекты

### 1. Раздвоенный и недеплоебельный migration graph — critical

- Файлы: две миграции 0008 с одним `down_revision` и одинаковым изменением schema/backfill.
- Фактическое поведение: Alembic возвращал два head; один revision ID не помещался в стандартный `alembic_version.version_num VARCHAR(32)`.
- Риск: блокировка штатного upgrade; при попытке применить обе ветви — повторный `ALTER TABLE`/constraint conflict.
- Исправление: удалена ошибочно упакованная `0008_plan_outcome_path_unavailable.py`; сохранён один совместимый head.

### 2. Backtest/promotion считали сделки, невозможные в live policy — high

- Live contract: `app/api/v1/recommendations.py` блокирует второй активный `ACCEPTED`/`ENTERED`/`PARTIAL` plan одного symbol в account scope.
- Research paths: `scripts/backtest.py::policy_backtest` и `app/ml/training.py::evaluate_policy_model` до исправления принимали новый hourly trade того же symbol до выхода предыдущего.
- Воспроизведение: два BTC-кандидата с decisions `t` и `t+1`, первый modeled exit в `t+2`. Baseline возвращал 2 trades; live acceptance разрешил бы 1.
- Риск: завышение trade count, искажение return/drawdown/concurrency и policy evidence, используемого auto-activation gate.
- Исправление: общий fail-closed фильтр одного активного symbol; re-entry разрешён на точной границе modeled exit.

### 3. Release provenance противоречил фактическому архиву — high

- `docs/QA_REPORT.md` исходного архива утверждал успешную проверку `SHA256SUMS` и наличие release history.
- Фактически manifest, changelog и patch-файл отсутствовали.
- Исправление: восстановлены `CHANGELOG.md`, `PATCH_1.8.32.md`, актуальный QA/report и пересчитанный manifest.

## Red → green

| Контракт | Red | Green |
|---|---|---|
| Revision ID / migration graph | baseline pytest: 1 failure; `alembic heads`: 2 heads | 2 migration-contract tests passed; single head `0008_outcome_path_unavailable` |
| Same-symbol overlap в backtest | regression test: `trades == 2`, ожидалось 1 | overlap blocked; `trades == 1`, counter = 1 |
| Same-symbol overlap в promotion evaluation | schema/behavior test failed на v6 и двух trades | schema v7; 1 trade, 1 blocked, corrected weighted R |
| Exit-boundary semantics | новый acceptance test | re-entry at `decision_time == prior_exit_time` passes; concurrency remains 1 |

## Post-check

| Проверка | Статус и результат |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py migrations` | PASSED |
| `python -m ruff check .` | PASSED — all checks passed |
| `python -m pytest -q` | PASSED — 410 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0008_outcome_path_unavailable` |
| Offline SQL `0007:0008` | PASSED — generated PostgreSQL DDL/backfill and 29-character version update |
| Release integrity / `SHA256SUMS` | PASSED — 159 files checked, 159 manifest entries |
| PostgreSQL integration suite | NOT RUN — separate safe PostgreSQL unavailable; 4 integration tests remain skipped in ordinary suite |
| Real upgrade/backfill/downgrade | NOT RUN — PostgreSQL server unavailable |

## Compatibility and operator actions

- Version: `1.8.32` (patch).
- No new dependency, `.env` variable, API endpoint/field or DB migration.
- Policy metric schema: `exit-time-open-gap-single-symbol-cohort-v7`; v6 evidence must be recalculated by the current trainer.
- Before migration, run `python -m alembic heads`; only `0008_outcome_path_unavailable` is valid.
- Active incumbent is not deactivated when candidate/re-evaluation fails.

## Residual risks

- No real PostgreSQL migration or integration execution in this environment.
- Research still lacks full historical order book/fills/funding timeline, operator latency/no-fill model, full walk-forward, drift/regime governance and PBO/DSR.
- An ad hoc strict mypy run is not a configured project gate and reports numerous typing/stub diagnostics; type-clean migration is a separate work package.
- Technical correctness and green tests do not establish profitability.
