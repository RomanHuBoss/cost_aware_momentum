# Iteration report — fail-closed counterfactual plan valuation

## 1. Входной архив и идентификация

- Вход: `cost_aware_momentum-main(1).zip`.
- SHA-256: `d86b3ca56d134b1ecf528398df2adf5e70812a26b85778d7bad3b871678790f7`.
- Исходная версия пакета/приложения: `1.7.5`.
- Python requirement: `>=3.12`; проверка выполнялась на Python 3.13.5.
- Исходный Alembic head: `0004_counterfactual_outcomes`.
- Исходный состав: 65 production Python files, 17 test files, 18 documentation files, 144 files total.
- Входной release содержал нежелательный `cost_aware_momentum.egg-info/` и прежний `SHA256SUMS`; они не переносятся как доверенный build state и исключаются/пересчитываются при упаковке.

## 2. Цель и критерии приемки

После этой итерации counterfactual valuation каждой execution-plan version должна fail-closed обрабатывать поврежденные numeric/cost/funding snapshot values, не публиковать non-finite P&L/R и не прерывать обработку других plan versions.

Критерии:

1. `NaN`, `Infinity`, отрицательные fees/reserves и невалидный funding snapshot не дают `VALUED`.
2. Invalid plan получает terminal status `INVALID_INPUT`, qty/P&L/cost/funding равны нулю, R отсутствует.
3. Диагностика сохраняет field-specific `validation_error`; валидные entry/exit market outcome не подменяются.
4. Поврежденная plan version не блокирует остальные rows в batch.
5. PostgreSQL check constraint допускает `INVALID_INPUT`; downgrade не уничтожает такие audit rows.
6. UI различает invalid snapshot от нулевого/безубыточного результата.
7. Ранее зеленые sizing, outcome, ML, API и frontend tests не регрессируют.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `PATCH_1.7.3.md`–`PATCH_1.7.5.md`, `pyproject.toml`, `.env.example`, архитектура, QA, compliance, traceability, model card, configuration, security, incident runbook, operator manual и релевантные части `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`.

Изменяемый поток:

`ExecutionPlan.qty/actual_stress_loss/sizing_snapshot.costs` → funding timeline validation → `estimate_plan_outcome()` → `PlanOutcome` PostgreSQL row → audit/outbox → API serializer → UI economics tab.

Market signal/outcome entry and exit prices остаются отдельным доверительным уровнем: при их повреждении substitute price не создается, ошибка возвращается в `invalid_plan_outcomes`.

## 4. Baseline до правок

Host environment:

| Команда | Статус | Существенный результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED (external environment) | MoviePy требует Pillow `<12`, установлен Pillow 12.2.0 |
| `python -m compileall -q app scripts tests manage.py` | PASSED | без вывода |
| `python -m ruff check .` | UNAVAILABLE | модуль Ruff отсутствовал |
| `python -m pytest -q` | FAILED (environment) | 6 collection errors из-за отсутствующего psycopg |
| `node --check web/js/app.js` | PASSED | без вывода |
| `alembic heads` | PASSED | `0004_counterfactual_outcomes` |
| `python manage.py doctor` | FAILED (environment) | project-local `.venv` отсутствовала |
| `python manage.py test --require-integration` | NOT RUN | wrapper остановился из-за отсутствующей project-local `.venv` |

После установки declared `.[dev]` в отдельное isolated environment:

| Команда | Статус | Результат |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | — |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 111 passed, 3 skipped, 20 warnings |
| `node --check web/js/app.js` | PASSED | — |
| `alembic heads` | PASSED | `0004_counterfactual_outcomes` |

Три skipped tests требуют отдельную PostgreSQL test database. SQLite/fake application database не использовалась.

## 5. Подтвержденный defect

**CONFIRMED DEFECT, severity high (operational/data-quality/financial reporting).**

- Файл: `app/services/outcomes.py`, `estimate_plan_outcome()`, `_funding_rate_for_holding_period()`, `_record_plan_outcome()`.
- Путь: immutable plan snapshot → Decimal conversion/comparison → outcome arithmetic → PostgreSQL/API.
- Фактическое поведение:
  - `qty=NaN` и `slippage_rate=NaN` вызывали `decimal.InvalidOperation`;
  - infinite stress loss/stop reserve проходили как `VALUED`;
  - `funding_rate=NaN` формировал non-finite net P&L;
  - non-finite per-settlement funding не отвергался;
  - `_record_plan_outcome()` не изолировал поврежденную plan version.
- Ожидание: zero-valued terminal invalid result с диагностикой и продолжение batch.
- Почему тесты не поймали: existing outcome tests покрывали valid LONG/SHORT, fees, funding count, legacy timeline и unsized plan, но не non-finite PostgreSQL/JSON boundary.

## 6. План и фактический diff

Production:

- `app/risk/math.py`: validators finite/positive/non-negative стали reusable public helpers.
- `app/services/outcomes.py`: numeric boundary, bounded funding count, `INVALID_INPUT`, per-plan isolation and diagnostics.
- `app/db/models.py`: расширен PlanOutcome status contract.
- `web/js/app.js`: operator label для invalid snapshot.
- `migrations/versions/0005_plan_outcome_invalid_input.py`: новый check-constraint head.

Tests:

- `tests/unit/test_counterfactual_outcomes.py`: 9 новых assertions/cases, включая persisted invalid row.
- `tests/integration_postgres/test_migrations_and_audit.py`: новый expected head и constraint contract.

Docs/version:

- `app/__init__.py`, `pyproject.toml`, `README.md`, `CHANGELOG.md`, `PATCH_1.7.6.md`.
- `docs/QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `ARCHITECTURE.md`, `OPERATOR_MANUAL.md`, `INCIDENT_RUNBOOK.md`, этот report.

Scope не расширялся до training labels, walk-forward, drift monitoring или orderbook impact.

## 7. Red → green evidence

Команда:

```text
python -m pytest -q tests/unit/test_counterfactual_outcomes.py
```

RED на исходном production code после добавления regression tests: `8 failed, 12 passed`. Существенные причины: `decimal.InvalidOperation`, ожидаемый `INVALID_INPUT` фактически `VALUED`, non-finite funding не отвергался, schema status отсутствовал.

GREEN после реализации: `21 passed`. Дополнительный async unit test подтверждает, что plan с `qty=NaN` создает ORM row `INVALID_INPUT`, `qty=0`, `estimated_net_pnl=0`, `counterfactual_r=None` и `validation_error=qty must be finite`.

## 8. Migration/API/config compatibility

- Новая версия: `1.7.6` (patch).
- Migration head: `0005_plan_outcome_invalid_input`.
- Upgrade расширяет check constraint без изменения существующих rows.
- Downgrade намеренно прекращается, если уже существуют `INVALID_INPUT` rows; audit data не удаляется и не relabelled.
- REST field set не изменен; `valuation_status` получает новое значение, valid rows сохраняют прежний контракт.
- Новых `.env` variables и зависимостей нет.
- Advisory-only, PostgreSQL-only и process boundaries сохранены.

## 9. Post-check

| Команда | Статус | Результат |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | — |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 120 passed, 3 skipped, 20 warnings |
| targeted outcome tests | PASSED | 21 passed |
| `node --check web/js/app.js` | PASSED | — |
| `alembic heads` | PASSED | `0005_plan_outcome_invalid_input` |
| `python manage.py doctor` | FAILED (environment) | project-local `.venv`/`.env`, PostgreSQL tools/service absent |
| PostgreSQL integration | NOT RUN | no isolated `TEST_DATABASE_URL`/test server |

## 10. Не удалось проверить

- Upgrade/downgrade migration на реальном PostgreSQL 16/17.
- Concurrent worker batch with actual corrupted PostgreSQL NUMERIC/JSONB rows.
- UI browser interaction; выполнен только JavaScript syntax check и schema-level unit coverage.
- Paper/shadow forward behavior и экономическое преимущество стратегии.

## 11. Остаточные риски

- Corrupted market signal/outcome entry/exit не получает fake PlanOutcome; он будет повторно диагностироваться до исправления исходной row.
- `INVALID_INPUT` является terminal audit result для конкретной plan version; автоматическое исправление legacy data намеренно отсутствует.
- PostgreSQL integration tests остаются непроверенными в этой среде.
- Полный intrabar training/backtest alignment, drift monitoring и live rollback остаются roadmap.

## 12. Rollback

1. Остановить API/worker/trainer.
2. Если `INVALID_INPUT` rows отсутствуют, выполнить `python manage.py downgrade 0004_counterfactual_outcomes`.
3. Вернуть код 1.7.5 и перезапустить процессы.
4. Если rows существуют, не удалять их автоматически: экспортировать/исследовать и принять отдельное data-retention решение; migration блокирует unsafe downgrade.

## 13. Следующий рекомендуемый work package

Минимальный multi-window walk-forward/OOS aggregation для barrier model с group-preserving timestamp split, purge/embargo и fold-level registry. Это более приоритетный следующий research gap, но он не реализован в данной итерации.
