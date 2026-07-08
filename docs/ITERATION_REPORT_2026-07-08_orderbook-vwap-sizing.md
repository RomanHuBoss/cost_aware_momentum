# Iteration report — orderbook VWAP sizing and acceptance correctness

Дата: 2026-07-08. Целевая версия: 1.52.2.

## 1. Входной архив и исходное состояние

- Архив: `cost_aware_momentum-main.zip`.
- SHA-256: `e71a4980babc3c6cbf2ace4842544983a109199c7f24dc39ad06c3338c67d788`.
- Исходная версия: 1.52.1.
- Python requirement: `>=3.12`; фактический Python: 3.13.5.
- Alembic head: `0018_inference_observations`.
- Входной состав: 273 файла; 98 production/script Python, 121 test Python, 14 docs files, 18 migration revisions.
- Во входном ZIP не обнаружены `.env`, credentials, caches, bytecode, venv, `*.egg-info`, dumps или реальные model artifacts.

## 2. Цель и критерии приёмки

После этой итерации execution plan должен ограничивать размер фактически доступным base quantity внутри impact limit, а fresh acceptance должен принимать математически корректный aggregate VWAP нескольких tick-aligned уровней без ослабления остальных fail-closed gates.

Критерии:

1. LONG sizing на asks `100×1 + 100.1×1` не запрашивает больше `2` base units.
2. SHORT sizing на bids `100×1 + 99.9×1` не запрашивает больше `2` base units.
3. Quantity-safe cap вычисляется независимо: `available_qty × min(best_price, worst_price)`.
4. Aggregate VWAP между тиками не отклоняется только из-за tick alignment.
5. Отдельные orderbook levels и immutable signal prices продолжают проверяться по tick size.
6. Acceptance использует exact fresh FULL-fill depth notional, а не planning-only conservative cap.
7. API, DB schema, `.env` и artifact contracts не меняются.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `PATCH_1.51.1.md`, `PATCH_1.52.0.md`, `PATCH_1.52.1.md`, `pyproject.toml`, `.env.example`, обязательные архитектурные/QA/compliance/traceability/security/operator/model documents и релевантные части `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`.

Изменяемый поток:

```text
OrderBookSnapshot bids/asks
  -> simulate_market_fill / orderbook_fill_for_qty
  -> orderbook_depth_notional_cap
  -> calculate_position_plan qty/notional
  -> immutable execution_quality evidence
  -> POST /api/v1/recommendations/{signal_id}/accept
  -> fresh exact FULL-fill VWAP + current depth
  -> validate_execution_plan_for_acceptance
  -> OperatorDecision context snapshot
```

Спецификация требует VWAP по доступной глубине, adverse-side execution и отсутствие двойного spread count; она не требует, чтобы weighted average нескольких валидных уровней сам совпадал с tick grid.

## 4. Baseline

| Команда | Результат |
|---|---|
| `python --version` | Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 850 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED: external venv не считается project-local `.venv` |
| integration tests | NOT RUN: отсутствует безопасная PostgreSQL test DB |

## 5. Подтверждённые дефекты

### HIGH — quote-notional depth cap завышал base quantity

Файл: `app/services/execution.py`, `orderbook_depth_notional_cap` и вызов в `create_execution_plan`.

Исходное поведение возвращало `sum(price_i × qty_i)`. Sizing затем делил cap на одну entry/reference price. Для LONG asks `100×1 + 100.1×1`:

```text
available_notional = 200.1
requested_qty after division/floor = 2.001
actual available_qty = 2
fill status = PARTIAL
```

Ожидаемое поведение: depth-limited plan не должен запрашивать quantity больше доступной. Существующие тесты проверяли fill simulation и single-level cases, но не обратное преобразование multi-level quote cap в base quantity.

### HIGH — aggregate VWAP ошибочно проверялся как биржевая limit price

Файл: `app/services/execution.py`, `validate_execution_plan_for_acceptance`.

Каждый уровень `100.0` и `100.1` валиден при tick `0.1`, но weighted average `100.05` находится между тиками. Исходный код применял `_is_step_aligned(entry, tick_size)` к aggregate VWAP и возвращал `409 PLAN_RECALCULATION_REQUIRED`.

Ожидаемое поведение: tick-aligned должны быть source levels и signal/order geometry; aggregate reporting/repricing VWAP не является выставляемой limit price.

## 6. План и фактический diff

Production:

- `app/services/execution.py`: quantity-safe conservative depth cap; снята только ошибочная aggregate-VWAP tick check.
- `app/api/v1/recommendations.py`: fresh acceptance использует actual `current_fill.available_notional` после exact FULL-fill.

Tests:

- новый `tests/unit/test_orderbook_vwap_sizing_integrity_2026_07_08.py`;
- расширен `tests/unit/test_execution_acceptance_safety.py` multi-level endpoint case.

Release/docs:

- версия 1.52.2, changelog, patch notes, README, operator manual, QA, compliance, traceability и этот report.
- migration/config/API changes отсутствуют.

## 7. Red → green

На исходном production code 1.52.1 новые четыре проверки дали `4 failed`:

```text
LONG cap: 200.1 != 200
SHORT cap: 199.9 != 199.8
aggregate VWAP rejected by instrument constraints
endpoint: 409 != 200
```

После production fix тот же набор дал `4 passed`.

Тестовые oracle независимы от исправляемой функции: ожидаемые caps рассчитаны вручную из base quantity и минимальной executable price; expected VWAP endpoint case равен `(100×1 + 100.1×1) / 2 = 100.05`.

## 8. Миграции и совместимость

- Alembic migration: не требуется.
- `.env`: без изменений.
- API request/response schema: без изменений.
- Model artifact schema: без изменений.
- Existing stored plans не переписываются; при acceptance они проходят fresh-state revalidation.
- Rollout: перезапустить API и inference worker.

## 9. Post-check

| Команда | Результат |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 854 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED: external venv не считается project-local `.venv` |
| PostgreSQL integration | NOT RUN: безопасная test DB отсутствует |
| `python -B manage.py release-check --write` | PASSED |
| `python -B manage.py release-check` | PASSED |
| ZIP test / clean re-extract / internal release-check | PASSED |

Baseline→post: `850 → 854 passed`; skipped и warnings не изменились.

## 10. Непроверенное

- PostgreSQL integration tests: безопасная отдельная test DB отсутствует.
- Live Bybit read-only smoke: сеть и credentials не использовались.
- Реальная fill probability, queue position и snapshot-to-manual-order latency не моделировались.
- Economic profitability и forward edge не заявляются.

## 11. Остаточные риски

Quantity-safe cap консервативен и может немного недоиспользовать quote liquidity из-за выбора минимальной executable price и последующего floor-to-step. Это безопасное направление ошибки. Snapshot может измениться после acceptance; поэтому advisory-only оператор всё равно обязан проверить актуальный стакан перед ручным ордером.

## 12. Rollback

1. Остановить API и inference worker.
2. Вернуть release 1.52.1; DB rollback не требуется.
3. Перезапустить процессы.
4. Учесть, что rollback возвращает ложные `PARTIAL`/409 для некоторых multi-level VWAP cases.

## 13. Следующий рекомендуемый work package

Отдельно исследовать 62 dependency deprecation warnings и подготовить compatibility patch до обновления NumPy/pandas/joblib, не смешивая его с торговой математикой.
