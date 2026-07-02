# QA Report — 1.8.33

Дата: 2026-07-02

## Входной архив

- Архив: `cost_aware_momentum-main(1).zip`.
- SHA-256: `200a4bca62367d97f4712816332dfb815cacdafafb29246bea7ee5bfd03087de`.
- Исходная версия: `1.8.32`; Python requirement: `>=3.12`.
- Фактический Alembic head: `0008_outcome_path_unavailable`.
- Утверждения о «20 + 7 + 18 ошибках» не сопровождались файлами, функциями, stack traces или воспроизводимыми примерами и поэтому не использовались как доказанные findings.

## Baseline до правок

Проверки выполнены в отдельном venv с установкой `-e .[dev]`.

| Проверка | Статус и результат |
|---|---|
| Python | PASSED — 3.13.5 |
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 410 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |

## Подтверждённые defects/gaps

### 1. Некалиброванный baseline мог стать actionable — critical

- Paths: `app/ml/runtime.py`, `app/services/signals.py`, `app/services/execution.py`.
- Baseline probabilities при нейтральных features: TP 0.34, SL 0.52, TIMEOUT 0.14.
- При стандартных fee/slippage/gap reserve и ATR 5% exact policy calculation давал `net RR 1.8131`, `EV/R 0.0885`; оба значения выше defaults.
- `create_execution_plan` до patch возвращал `ACTIONABLE`; acceptance не проверял model provenance.
- Влияние: некалиброванный diagnostic fallback мог обойти смысл model quality gate и привести к ручному входу.

### 2. TIMEOUT return был скрытой универсальной эконометрической гипотезой — high

- `-0.002` был default-аргументом в risk math/training/backtest и не являлся операторской policy setting.
- Он влиял на direction selection, EV/R, plan acceptance и promotion evidence, но не сохранялся как самостоятельная immutable assumption.
- Влияние: изменение требовало правки кода, а API/replay могли неявно пересчитать экономику по иной гипотезе.

### 3. Minimum trades управлял также independent cohorts — medium

- `app/ml/lifecycle.py::evaluate_quality_gate` сравнивал и `policy_trades`, и `policy_cohorts` с `AUTO_TRAIN_MIN_POLICY_TRADES`.
- Влияние: оператор не мог независимо задать статистический минимум временных когорт; причина gate была конфигурационно неоднозначной.

## Red → green

| Regression contract | Red до production fix | Green после fix |
|---|---|---|
| Baseline plan diagnostic-only | фактически `ACTIONABLE`, ожидался `NO_TRADE` | plan `NO_TRADE`, явное warning |
| Independent cohort threshold | candidate ошибочно отклонён по trade threshold | `AUTO_TRAIN_MIN_POLICY_COHORTS` применяется отдельно |
| Explicit TIMEOUT economics | `unexpected keyword argument timeout_return_rate` | assumption проходит через exact signal economics |
| Production baseline override | unsafe override принимался как ignored extra | configuration rejected fail-closed |
| Legacy acceptance | отсутствовала provenance block | baseline actionable plan rejected before repricing |
| Serializer parity | hidden default | persisted timeout assumption used |

## Post-check

| Проверка | Статус и результат |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py migrations` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 416 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — one head `0008_outcome_path_unavailable` |
| `python manage.py doctor` | FAILED ENVIRONMENT — `.env`, PostgreSQL tools/server and production secrets unavailable; Python/directories passed |
| `python manage.py test --require-integration` | NOT RUN — requires safe `TEST_DATABASE_URL` or `POSTGRES_ADMIN_URL` |

## Compatibility and operator actions

- Version: `1.8.33` (patch).
- Migration: none.
- Add explicitly to `.env` or accept safe defaults:
  - `ALLOW_BASELINE_ACTIONABLE=false`
  - `TIMEOUT_GROSS_RETURN_RATE=-0.002`
  - `AUTO_TRAIN_MIN_POLICY_COHORTS=20`
- Restart API, inference worker and trainer.
- Do not lower ML/policy gates merely because a daily candidate fails; inspect exact candidate `quality_gate.reasons` and acquire independent OOS/forward evidence.

## Residual risks

- Specific user losses and candidate failures were not reproducible without PostgreSQL state, decision/fill journals, candidate artifacts/metrics and contemporaneous market snapshots.
- No real PostgreSQL integration, migration upgrade/downgrade, or restore test was possible.
- Research still lacks full historical order book/fills/funding path, operator latency/no-fill model, full walk-forward, drift/regime governance and PBO/DSR.
- `manage.py` currently surfaces a Python traceback after expected non-zero diagnostic/test-runner exits; this is an operational UX issue, not fixed in this work package.
- Correct code and green tests do not establish economic edge or future profitability.
