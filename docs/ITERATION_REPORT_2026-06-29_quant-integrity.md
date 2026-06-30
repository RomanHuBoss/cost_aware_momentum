# Отчет итерации 2026-06-29 — quantitative integrity

## 1. Вход и идентификация

- Входной архив: `cost_aware_momentum-main.zip`.
- SHA-256 входного архива: `81e4571b8377b11bfedbbf8f840c12144e05dfda148c0a64d1882eaed1aff25c`.
- Исходная версия: `1.8.10`.
- Python requirement: `>=3.12`; проверка выполнена на Python `3.13.5`.
- Alembic revisions: `0001`–`0006`; единственный head — `0006_manual_trade_remaining_risk`.
- До изменения: 68 production Python-файлов, 31 test Python-файл, 16 файлов верхнего уровня `docs/`.
- Входной release tree не содержал `.env`, реальных credentials, model artifacts, `.venv`, caches или dumps. Рабочая `.audit-venv` создавалась только для проверки и исключена из release.

## 2. Цель и критерии приемки

Цель: после итерации все policy/risk/outcome/manual-journal расчеты в изменяемом потоке должны сохранять горизонт, временную доступность и числовые инварианты fail-closed, что подтверждается независимыми red → green тестами и полным regression suite.

Критерии:

1. Перекрывающиеся H-часовые решения не считаются H полнокапитальными независимыми ставками в policy drawdown/total R.
2. Promotion gate принимает только policy metrics с явной schema и horizon, совпадающими с artifact.
3. TP/TIMEOUT return и `label_end_time` согласованы с barrier/horizon до direction ranking.
4. Execution-plan funding считается от текущего planning time; неизвестный interval при пересекаемом ненулевом settlement блокирует plan.
5. Fractional/boolean/non-positive leverage не усекается молча.
6. Hourly/intrabar outcome bars имеют точный interval и когерентный OHLC.
7. Manual entry/close timestamp не naive и не в будущем.
8. Полный unit suite, static checks и release integrity проходят; PostgreSQL-only/advisory-only границы не меняются.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `CHANGELOG.md`, `PATCH_1.8.10.md`, `pyproject.toml`, `.env.example`, `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`, релевантные части встроенной DOCX-спецификации и production/tests изменяемых модулей.

Потоки:

- candles → barrier metadata → candidate/incumbent probabilities → direction ranking → exit-time policy metrics → quality gate → registry;
- ticker/spec + signal + capital profile → planning-time funding/cost scenario → Decimal sizing/EV/liquidation → execution plan snapshot;
- confirmed hourly/intrabar candles → barrier evaluator → signal/plan outcomes → API/UI/audit;
- operator payload → chronology/time validation → fills/manual trade → realized P&L/open risk.

## 4. Baseline до правок

Изолированное окружение проекта:

| Команда | Результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 252 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |

Системный Python до изоляции был непригоден как baseline: отсутствовали `psycopg` и Ruff, pytest завершался 16 collection errors, а глобальный `pip check` сообщал о стороннем конфликте Pillow/moviepy. Эти ошибки не приписывались проекту.

`python manage.py doctor` и `python manage.py test --require-integration` не запускались: безопасная runtime `.env` и отдельная PostgreSQL test database отсутствовали.

## 5. Подтвержденные дефекты

| № | Severity | Доказательство и влияние |
|---:|---|---|
| 1 | CRITICAL | `app/ml/training.py::evaluate_policy_model`: каждый hourly cohort добавлял полный R при H-часовом overlap. Для двух последовательных прибыльных решений при H=2 total был 2R вместо 1R capital-sleeve-normalized; drawdown также завышался в H раз. Это могло ошибочно блокировать/пропускать candidate. |
| 2 | HIGH | `app/ml/lifecycle.py::evaluate_quality_gate`: promotion принимал policy metrics без schema/horizon, поэтому несовместимые старые и новые accounting semantics сравнивались как одинаковые. |
| 3 | HIGH | `validate_policy_evaluation_metadata`: TP мог иметь return ниже barrier; TIMEOUT мог пересечь TP/SL и оставаться TIMEOUT. Поврежденный realized oracle влиял на candidate/incumbent comparison. |
| 4 | HIGH | Там же `label_end_time` проверялся только как верхняя граница exit, но мог не соответствовать configured horizon, нарушая purge/availability semantics. |
| 5 | CRITICAL | `app/services/execution.py::create_execution_plan`: recalculated plan использовал `signal.funding_rate_scenario`, рассчитанный в прошлый publish time. Уже прошедшие settlements могли учитываться повторно, а новые — пропускаться в risk/EV/sizing. |
| 6 | HIGH | `app/risk/math.py`: `int(leverage)` превращал 1.9 в 1 и отрицательные/нулевые значения в fallback. Некорректный операторский/импортированный input не блокировался однозначно. |
| 7 | MEDIUM | `app/services/outcomes.py`: hourly evaluator принимал 30-minute bar, изменяя число/время наблюдений и barrier path. |
| 8 | MEDIUM | Там же close мог находиться выше high или ниже low; такой OHLC использовался для TIMEOUT/outcome valuation. |
| 9 | HIGH | `app/api/v1/trades.py`: future-dated entry/close fill проходил chronology checks и загрязнял realized P&L, open-risk timeline и последующую эконометрику. |
| 10 | HIGH | Plan-time funding при известном ненулевом settlement и отсутствующем interval мог быть не доказан; прежний helper возвращал ноль в аналогичной ситуации. Новая граница блокирует execution plan. |

Утверждение внешних экспертов о «12 критических и 8 средних» не было снабжено доказательствами. В этой итерации подтверждены именно перечисленные десять defect groups; их severity назначена по фактическому влиянию, без подгонки под заявленные числа.

## 6. Изменения по файлам

Production:

- `app/ml/training.py` — horizon-aware policy schema/sleeves; strict barrier/horizon metadata.
- `app/ml/lifecycle.py` — candidate/incumbent schema/horizon gate.
- `app/services/execution.py` — planning-time funding reprojection и diagnostic snapshot.
- `app/risk/math.py` — strict integer leverage.
- `app/services/outcomes.py` — interval/OHLC validation; evaluation v3.
- `app/api/v1/trades.py` — aware/nonfuture manual fills.
- `app/__init__.py`, `pyproject.toml` — version 1.8.11.

Tests:

- `tests/unit/test_quant_integrity_2026_06_29.py` — 11 независимых регрессионных cases.
- `tests/unit/test_model_lifecycle.py` — legacy policy-schema rejection и обновленные fixtures.
- `tests/unit/test_model_artifact_recovery.py` — current policy metric contract in artifact fixture.
- `tests/unit/test_training.py` — exact barrier oracle и horizon-normalized drawdown expectation.

Docs/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.8.11.md`.
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/OPERATOR_MANUAL.md`, `docs/ARCHITECTURE.md`.
- этот отчет и пересчитанный `SHA256SUMS`.

Migration/API/env:

- новая migration отсутствует; head остается `0006`;
- HTTP paths и JSON schemas не изменены; invalid timestamps теперь возвращают HTTP 422;
- новые `.env` переменные отсутствуют.

## 7. Red → green evidence

На unmodified 1.8.10:

- `test_quant_integrity_red.py`: 7 failed — horizon argument/accounting, TP mismatch, label horizon, fractional liquidation leverage, non-hourly/OHLC bars, future fill;
- отдельный funding projection test: 1 failed (`ImportError`, функция/контракт отсутствовали);
- additional red module: 3 failed — fractional sizing был `ACTIONABLE`, TIMEOUT barrier mismatch не отклонялся, unknown funding interval contract отсутствовал;
- policy schema gate: 1 failed — legacy payload проходил с `passed=True`.

Итого: 12/12 focused cases red на входной версии. После реализации соответствующие 12/12 green. Тесты используют вручную заданные barrier returns, horizon sleeves, OHLC и timestamps, а не output проверяемой функции как oracle.

## 8. Post-check

| Команда | Результат |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 264 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py release-check` | PASSED — clean manifest, exact count recorded by release-check |
| ZIP integrity/re-extraction | PASSED — archive test and clean re-extraction verified |

## 9. Непроверенное

- PostgreSQL integration tests и migration upgrade/downgrade — нет отдельной `TEST_DATABASE_URL`/admin database.
- `manage.py doctor` — нет безопасной runtime `.env`/PostgreSQL instance.
- Bybit network smoke — не требовался для внутреннего deterministic fix и не выполнялся.
- Forward/paper экономический результат — отсутствует; техническая корректность не доказывает edge.

## 10. Остаточные риски

1. Counterfactual `PlanOutcome` считает funding по сохраненному plan snapshot и предполагаемой periodicity, а не сверяет каждую settlement rate с исторической таблицей `FundingRate`. Это подтвержденный эконометрический gap, но его исправление требует отдельного DB-query/data-availability work package и PostgreSQL integration tests.
2. Candidate promotion использует один chronological final holdout в повторяющихся training cycles; полноценный multi-fold walk-forward/OOF aggregation и governance однократного final holdout отсутствуют.
3. Historical point-in-time universe membership, historical order-book/no-fill/partial fills, operator latency, PBO/DSR и live drift/auto-rollback не реализованы.
4. Existing `primary-barrier-intrabar-v2` outcomes не переписываются; новые evaluations используют v3. Исторические comparisons должны учитывать version.

## 11. Rollback

1. Остановить API/worker/trainer.
2. Восстановить код/документацию версии 1.8.10 и прежний model artifact/registry state при необходимости.
3. DB downgrade не нужен: schema не менялась.
4. Не смешивать policy metrics `exit-time-horizon-sleeves-v2` с legacy payloads; после rollback переоценить candidate/incumbent старым кодом либо оставить candidate inactive.
5. Outcomes v3 остаются audit records; не удалять их задним числом.

## 12. Следующий рекомендуемый work package

Заменить snapshot-экстраполяцию counterfactual funding на point-in-time join фактических `market.funding_rates` по каждому пересеченному settlement, с explicit missing-rate status, PostgreSQL integration tests и migration/API review только при необходимости.
