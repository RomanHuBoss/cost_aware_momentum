# Отчет об итерации 1.7.5 — fail-closed numeric sizing inputs

Дата: 28 июня 2026 г.

Входной архив: `cost_aware_momentum-main.zip`

SHA-256 входного архива:

```text
fe1f05616b7099c384d865d6eb25e95b9aab5da27b511cb1d0d5214487e3ce4c
```

Фактический корень: `cost_aware_momentum-main`

Версия до изменения: `1.7.4`

Версия после изменения: `1.7.5`

Python requirement: `>=3.12`

Alembic migrations: `0001_initial`, `0002_single_current_signal_per_symbol`, `0003_single_active_model`, `0004_counterfactual_outcomes`; единственный head — `0004_counterfactual_outcomes`.

Исходные counts: 65 production Python files (`app`, `scripts`), 17 test Python files, 17 documentation files в `docs/`.

Исходный release boundary содержал неожиданные `cost_aware_momentum.egg-info` и устаревший `SHA256SUMS`; они исключаются из нового архива. Реальные model artifacts, dumps, `.env` и credentials не обнаружены. Каталоги `models`, `reports`, `backups` содержали только `.gitkeep`.

## Цель и критерии приемки

После этой итерации position-sizing boundary должен до любой финансовой арифметики fail-closed проверять числовые входы и возвращать безопасный нулевой план вместо исключения либо исполнимого результата.

Критерии:

1. `effective_capital`, `risk_rate`, instrument steps/minima/max leverage должны быть положительными и finite.
2. Fee, slippage и stop-gap reserve должны быть finite и неотрицательными; funding может быть finite signed.
3. Available margin и optional notional caps должны быть finite и неотрицательными.
4. `margin_reserve_rate` допускается только в диапазоне `[0, 1)`.
5. Любой invalid numeric input возвращает `BLOCKED_INVALID_INPUT`, нулевые qty/notional/loss/margin и field-specific diagnostic.
6. Invalid-plan capital/risk outputs также должны быть finite, чтобы `NaN`/`Infinity` не попадали в PostgreSQL/API.
7. Valid sizing examples сохраняют прежние результаты; directional geometry contract версии 1.7.4 не регрессирует.
8. Полный доступный suite остается зеленым; advisory-only, PostgreSQL-only и process boundaries сохраняются.

## Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `PATCH_1.7.1.md`–`PATCH_1.7.4.md`, `pyproject.toml`, `.env.example`, `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`, master prompt, production modules и tests изменяемой области.

Проверенный поток:

```text
Bybit read-only instrument/ticker/account snapshots + capital profile
→ app/services/execution.py собирает capital, margin, portfolio/liquidity caps и costs
→ app/risk/math.py::calculate_position_plan
→ PostgreSQL advisory.execution_plans
→ API serializer / operator UI
```

API schemas валидируют штатно введенный capital profile, но service boundary также получает значения из PostgreSQL, account snapshots, instrument history и imported/legacy rows. Поэтому Pydantic-проверка одного HTTP endpoint не является достаточным инвариантом финансовой арифметики.

## Baseline до правок

Первый запуск в общей host-среде зафиксирован отдельно:

- `python -m pip check` — FAILED из-за внешнего конфликта `moviepy 2.2.1` / `pillow 12.2.0`, отсутствующего в зависимостях проекта;
- Ruff отсутствовал;
- psycopg отсутствовал, поэтому pytest завершился 6 collection errors.

Для воспроизводимого baseline создано отдельное окружение и установлены declared dependencies командой `python -m pip install -e '.[dev]'`.

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | без вывода |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 103 passed, 3 skipped, 20 warnings |
| `node --check web/js/app.js` | PASSED | без вывода |
| `python -m alembic heads` | PASSED | `0004_counterfactual_outcomes (head)` |
| `python manage.py doctor` | FAILED (environment) | без project-local `.venv` management wrapper остановился до диагностики; при временном подключении isolated venv выявлены отсутствующие `.env`, безопасные secrets, PostgreSQL tools/service |
| `python manage.py test --require-integration` | NOT RUN | отсутствуют `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` и отдельная PostgreSQL test database |

Три skipped test — PostgreSQL integration tests. SQLite и fake application database не использовались.

## Подтвержденный дефект

Классификация: `CONFIRMED DEFECT`.

Severity: `high` — необработанные исключения и fail-open cost arithmetic на финансовом risk boundary.

Файл и функция:

- `app/risk/math.py::calculate_position_plan`;
- consumer `app/services/execution.py::create_execution_plan`.

Минимальные воспроизводимые случаи исходной версии:

```text
effective_capital=NaN
→ decimal.InvalidOperation при сравнении effective_capital <= 0

available_margin=NaN или liquidity_notional_cap=NaN
→ decimal.InvalidOperation внутри max(...)

qty_step=0
→ необработанный ValueError из floor_to_step()

risk_rate=Infinity
→ функция возвращает non-blocked LIMITED plan

fee_rate_round_trip=-0.0011
→ отрицательная комиссия уменьшает downside и возвращается ACTIONABLE plan
```

Ожидаемое поведение: любой non-finite/domain-invalid обязательный input блокируется до sizing; отрицательные cost reserves не улучшают edge; в plan не остаются non-finite значения.

Влияние:

- worker/API transaction может завершиться исключением и не сохранить план;
- corrupted/imported data может сформировать non-blocked sizing;
- отрицательные costs искусственно увеличивают безопасный notional;
- `NaN`/`Infinity` могут перейти к persistence/serialization boundary.

Почему существующие тесты не поймали проблему: `tests/unit/test_risk_math.py` проверял valid arithmetic, directional geometry, rounding и zero caps, но не проверял non-finite capital/margin/caps, invalid exchange constraints или отрицательные costs.

## План изменения

Production scope: один модуль `app/risk/math.py`.

Test scope: `tests/unit/test_risk_math.py`.

Migration/config/API: не меняются.

Решение:

1. централизовать finite/positive/non-negative Decimal validation;
2. нормализовать все sizing inputs до расчетов;
3. возвращать единый безопасный zero-sized plan с диагностикой;
4. сохранить отдельный `INVALID_GEOMETRY` для directional barrier ошибок;
5. не изменять formulas и результаты valid plan.

## Red → green evidence

До production-изменения добавлены семь parametrized regression cases и один positive control для signed funding.

RED command:

```text
python -m pytest -q tests/unit/test_risk_math.py
```

RED result:

```text
7 failed, 19 passed
```

Существенные причины:

- capital, available margin и notional cap с `NaN` дали `decimal.InvalidOperation`;
- `qty_step=0` дал необработанный `ValueError`;
- infinite risk rate вернул `LIMITED`;
- `margin_reserve_rate=1` и отрицательная fee не были заблокированы.

GREEN targeted command:

```text
python -m pytest -q tests/unit/test_risk_math.py
```

GREEN result:

```text
26 passed
```

Новый positive control подтверждает, что finite отрицательный funding rate по-прежнему допустим и не ошибочно классифицируется как invalid cost.

## Реализация и фактический diff

### Production

- `app/risk/math.py`
  - добавлены `_finite_decimal`, `_positive_finite_decimal`, `_nonnegative_finite_decimal`;
  - добавлен безопасный constructor `_blocked_invalid_position_plan`;
  - до arithmetic валидируются capital/risk, fee/slippage/reserve/funding, instrument constraints, margin reserve и optional caps;
  - invalid responses содержат нулевые qty/notional/loss/margin и finite capital/risk values;
  - valid calculations, floor rounding, min-order, margin, liquidity и portfolio statuses сохранены.

### Tests

- `tests/unit/test_risk_math.py`
  - `NaN` effective capital;
  - infinite risk rate;
  - `NaN` available margin;
  - invalid `margin_reserve_rate=1`;
  - `NaN` liquidity cap;
  - zero `qty_step`;
  - negative fee reserve;
  - positive control для signed finite funding.

### Version/docs/release

- `app/__init__.py`, `pyproject.toml` → `1.7.5`;
- `CHANGELOG.md`;
- `PATCH_1.7.5.md`;
- `README.md`;
- `docs/QA_REPORT.md`;
- `docs/SPEC_COMPLIANCE.md`;
- `docs/TRACEABILITY.md`;
- данный iteration report;
- final ZIP исключает stale `SHA256SUMS`, `cost_aware_momentum.egg-info` и test/build caches.

Compatibility:

- новая Alembic migration не требуется;
- `.env` не меняется;
- REST schemas и persisted schema не меняются;
- valid inputs сохраняют прежние numerical results;
- invalid legacy/imported data намеренно меняет поведение с exception/fail-open на block.

## Post-check

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | без вывода |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 111 passed, 3 skipped, 20 warnings |
| targeted risk tests | PASSED | 26 passed |
| `node --check web/js/app.js` | PASSED | без вывода |
| `python -m alembic heads` | PASSED | `0004_counterfactual_outcomes (head)` |
| package/app version | PASSED | `1.7.5` / `1.7.5` |
| forbidden Bybit write/order endpoint scan | PASSED | client содержит только GET public/read-only account methods; order create/amend/cancel methods отсутствуют |
| whitespace check | PASSED | whitespace errors не обнаружены |
| `python manage.py doctor` | FAILED (environment) | 6 failures: `.env`, default secrets, `psql`, `pg_dump`, `pg_restore`, PostgreSQL connection |
| `python manage.py test --require-integration` | NOT RUN | command остановился: требуется `POSTGRES_ADMIN_URL` или `TEST_DATABASE_URL` |

Ни один ранее зеленый unit test не стал красным. Три integration tests корректно skipped в обычном suite.

## Непроверенное и остаточные риски

- PostgreSQL integration не выполнена без отдельной test database; unit suite не заменяет фактический ORM transaction flow.
- `doctor` не может пройти без локальной PostgreSQL service, native tools, `.env` и non-default secrets.
- Source ingestion (`market_data.py`) по-прежнему может сохранить некорректный external/imported Decimal; current patch гарантирует fail-closed execution sizing, но не заменяет pre-persistence data-quality validation.
- Settings-level risk/cost fields не получили отдельный comprehensive finite/domain validator в этой итерации; execution sizing блокирует unsafe values, но startup fail-fast остается отдельным work package.
- Техническая корректность sizing не доказывает прибыльность стратегии.

## Rollback

1. Остановить API, worker и trainer.
2. Вернуть файлы версии 1.7.4.
3. Перезапустить процессы; downgrade migration и `.env` изменения не требуются.
4. Учесть, что rollback снова допускает исключения/fail-open sizing при non-finite или отрицательных numeric inputs.

## Следующий рекомендуемый work package

Добавить pre-persistence и startup validation для внешних instrument/account snapshots и всех Settings risk/cost полей: отклонять non-finite/domain-invalid данные при ingestion/config load, создавать data-quality diagnostics и не полагаться только на последнюю execution boundary.

## Текст коммита

```text
fix(risk): fail closed on invalid sizing inputs

- validate finite capital, risk, costs, instrument constraints, margin and caps
- return zero-sized BLOCKED_INVALID_INPUT diagnostics instead of exceptions or fail-open plans
- preserve signed funding and valid sizing arithmetic
- add red-to-green regression tests and release documentation
```
