# Отчет об итерации 1.7.4 — fail-closed directional geometry

Дата: 28 июня 2026 г.

Входной архив: `cost_aware_momentum-main(5).zip`

SHA-256 входного архива:

```text
7a6149eb3e5a3a61350836bbe50717edadea9fbeaf75257a77d654050c6fca54
```

Фактический корень: `cost_aware_momentum-main`

Версия до изменения: `1.7.3`

Версия после изменения: `1.7.4`

Python requirement: `>=3.12`

Alembic migrations: `0001_initial`, `0002_single_current_signal_per_symbol`, `0003_single_active_model`, `0004_counterfactual_outcomes`; единственный head — `0004_counterfactual_outcomes`.

Исходные counts: 65 production Python files (`app`, `scripts`), 17 test Python files, 15 documentation Markdown files.

Исходный release boundary содержал неожиданный `cost_aware_momentum.egg-info`; он исключен из нового архива. Реальные model artifacts, dumps, `.env` и credentials не обнаружены. Каталоги `models`, `reports`, `backups` содержали только `.gitkeep`.

## Цель и критерии приемки

После этой итерации risk/execution boundary должен fail-closed отвергать инвертированную LONG/SHORT геометрию цен и не создавать ненулевой исполнимый размер для логически неверного плана.

Критерии:

1. LONG принимает только `stop < entry < take_profit`.
2. SHORT принимает только `take_profit < entry < stop`.
3. Неположительные, `NaN` и `Infinity` цены отвергаются как invalid input.
4. Sizing при invalid geometry возвращает `BLOCKED_INVALID_INPUT`, нулевые qty/notional/loss и диагностическую причину.
5. Execution plan не маскирует invalid-input block статусом `NO_TRADE` или liquidation status.
6. Manual fill, расположенный за stop-границей, получает HTTP 422, а не server error.
7. Risk sizing и counterfactual outcome используют один validator.
8. Полный доступный suite не регрессирует; advisory-only и PostgreSQL-only границы сохраняются.

## Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `PATCH_1.7.0.md`–`PATCH_1.7.3.md`, `pyproject.toml`, `.env.example`, архитектурная, QA, compliance, traceability, model, configuration, security, incident и operator документация, а также production/tests изменяемой области.

Проверенный поток:

```text
Bybit read-only ticker + confirmed candle features
→ app/services/signals.py строит direction, entry, SL, TP
→ app/risk/math.py вычисляет downside/upside, net R/R, EV
→ app/services/execution.py рассчитывает profile-dependent sizing
→ PostgreSQL ExecutionPlan
→ API/UI и журнал ручных fills
→ app/services/outcomes.py оценивает counterfactual barrier outcome
```

До исправления signal generator создавал корректные барьеры, но risk boundary не защищался от corrupted/imported/legacy row либо будущей регрессии генератора. Outcome boundary имел отдельную строгую проверку, поэтому одинаковые данные могли быть приняты sizing и позднее отвергнуты outcome evaluator.

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
| `python -m pytest -q` | PASSED | 96 passed, 3 skipped, 20 warnings |
| `node --check web/js/app.js` | PASSED | без вывода |
| `python -m alembic heads` | PASSED | `0004_counterfactual_outcomes (head)` |
| `python manage.py doctor` | FAILED (environment) | отсутствуют `.env`, замененные secrets, `psql`/`pg_dump`/`pg_restore` и PostgreSQL service |
| `python manage.py test --require-integration` | NOT RUN | отсутствуют `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` и отдельная PostgreSQL test database |

Три skipped test — PostgreSQL integration tests. SQLite и fake database не использовались.

## Подтвержденный дефект

Классификация: `CONFIRMED DEFECT`.

Severity: `high` — неверная fail-open семантика на финансовом risk boundary, хотя штатный signal generator формирует корректные уровни.

Файлы и функции:

- `app/risk/math.py::stress_downside_rate`;
- `app/risk/math.py::upside_rate`;
- `app/risk/math.py::net_rr_and_ev`;
- `app/risk/math.py::calculate_position_plan`;
- consumer `app/services/execution.py::create_execution_plan`.

Фактическое поведение:

```text
LONG entry=100, stop=101, TP=110
→ abs(entry-stop)/entry = 1%
→ downside считается положительным
→ position sizing получает ненулевой risk notional
```

Аналогично LONG TP ниже entry и обе инверсии SHORT превращались в положительную «дистанцию». Тип `Literal` не выполняет runtime validation. Полная geometry не передавалась в sizing, поскольку `calculate_position_plan()` не принимал take-profit.

Ожидаемое поведение: неверная directional geometry блокируется до расчета RR/EV и position size; не создается фиктивно исполнимый размер.

Почему существующие тесты не поймали проблему: `tests/unit/test_risk_math.py` проверял только корректные LONG/SHORT примеры, симметрию PnL, funding, rounding и caps. Invalid directional barriers отсутствовали. Outcome tests использовали собственный validator и не проверяли согласованность с risk sizing.

## Red → green evidence

До production-изменения в `tests/unit/test_risk_math.py` добавлены проверки четырех инвертированных LONG/SHORT geometry и TP-aware sizing block.

RED command:

```text
python -m pytest -q tests/unit/test_risk_math.py
```

RED result:

```text
5 failed, 11 passed
```

Существенные причины:

- четыре случая `net_rr_and_ev()` не вызвали `ValueError`;
- `calculate_position_plan()` завершился `TypeError`, поскольку не имел параметра `take_profit` и не мог проверять полный контракт.

GREEN targeted command:

```text
python -m pytest -q tests/unit/test_risk_math.py tests/unit/test_counterfactual_outcomes.py tests/unit/test_intrabar_outcomes.py
```

GREEN result после добавления non-finite acceptance cases:

```text
37 passed
```

## Реализация и фактический diff

### Production

- `app/risk/math.py`
  - добавлены `_direction_sign`, `_positive_finite_price`, `validate_directional_geometry`;
  - directional distances рассчитываются формулами LONG/SHORT без `abs()`;
  - `gross_pnl` и funding отклоняют unsupported direction;
  - RR/EV проверяет entry/SL/TP до вычислений;
  - sizing принимает optional TP и возвращает zero-sized `BLOCKED_INVALID_INPUT` при ошибке geometry.
- `app/services/execution.py`
  - TP1 передается в sizing;
  - любой `BLOCKED_*` plan имеет приоритет над policy `NO_TRADE`;
  - invalid input не участвует в liquidation-distance arithmetic.
- `app/api/v1/trades.py`
  - invalid actual fill geometry преобразуется в HTTP 422.
- `app/services/outcomes.py`
  - удален дублирующий validator; используется единый risk contract.

### Tests

- `tests/unit/test_risk_math.py`
  - invalid LONG stop;
  - invalid LONG TP;
  - invalid SHORT stop;
  - invalid SHORT TP;
  - zero-sized blocked plan;
  - `NaN` и `Infinity` barriers.

### Version/docs/release

- `app/__init__.py`, `pyproject.toml` → `1.7.4`;
- `CHANGELOG.md`;
- `PATCH_1.7.4.md`;
- `README.md`;
- `docs/QA_REPORT.md`;
- `docs/SPEC_COMPLIANCE.md`;
- `docs/TRACEABILITY.md`;
- данный iteration report;
- `SHA256SUMS` пересчитывается после финальной очистки.

Migration/config/API compatibility:

- новая Alembic migration не требуется;
- `.env` не меняется;
- REST schemas не меняются;
- valid geometry сохраняет прежние числовые результаты;
- invalid legacy/imported data намеренно меняет поведение с fail-open/exception на block/422.

## Post-check

| Команда | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | без вывода |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 103 passed, 3 skipped, 20 warnings |
| targeted risk/outcome tests | PASSED | 37 passed |
| `node --check web/js/app.js` | PASSED | без вывода |
| `python -m alembic heads` | PASSED | `0004_counterfactual_outcomes (head)` |
| package/app version | PASSED | `1.7.4` / `1.7.4` |
| forbidden Bybit order endpoint scan | PASSED | write/order endpoints не обнаружены |
| whitespace check | PASSED | whitespace errors не обнаружены |
| `python manage.py doctor` | FAILED (environment) | `.env`, safe secrets, PostgreSQL tools/service отсутствуют |
| `python manage.py test --require-integration` | NOT RUN | отдельная PostgreSQL test database не настроена |

Ни один ранее зеленый unit test не стал красным. Три integration tests корректно skipped в обычном suite.

## Непроверенное и остаточные риски

- PostgreSQL integration не выполнена без отдельной test database; unit suite не заменяет проверку ORM transaction flow.
- `doctor` не может пройти без локальной PostgreSQL service, native tools, `.env` и non-default secrets.
- Default worker generator создает корректную geometry, но в PostgreSQL нет отдельного DB CHECK constraint для cross-column direction-dependent barrier ordering; текущая защита находится в service/risk boundary.
- Manual endpoint HTTP 422 path проверен кодом и общей статикой, но отдельный DB-backed API integration test отсутствует.
- Техническая корректность проверки не доказывает прибыльность стратегии.

## Rollback

1. Остановить API, worker и trainer.
2. Вернуть файлы версии 1.7.3.
3. Перезапустить процессы; downgrade migration не требуется.
4. Учесть, что rollback снова допускает fail-open directional arithmetic; не использовать corrupted/imported signals без внешней валидации.

## Следующий рекомендуемый work package

Согласовать training/backtest labels с post-event intrabar semantics: точечно использовать доступные 1/3/5-minute windows для hourly TP/SL ambiguity в dataset generation и OOS evaluation, сохраняя fail-closed при неполной истории. Это отдельная ML/temporal итерация и в текущий patch не включена.

## Текст коммита

```text
fix(risk): reject inverted directional price geometry

- validate finite LONG and SHORT entry, stop and take-profit ordering
- block invalid sizing with zero quantity and preserve the block before policy status
- return HTTP 422 for manual fills beyond the directional stop boundary
- share one geometry contract between risk sizing and outcome evaluation
- add red-to-green regression coverage and release documentation
```
