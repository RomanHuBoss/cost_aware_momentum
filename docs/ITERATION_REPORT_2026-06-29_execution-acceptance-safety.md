# Итерационный отчет — execution acceptance safety

Дата: 2026-06-29
Релиз: 1.8.7
Scope: fail-closed revalidation и сериализация риска при принятии execution plan

## 1. Входной архив и исходное состояние

- Архив: `cost_aware_momentum-main(1).zip`
- SHA-256: `06906a80fd269d7e0416f8a242e30c712fdbab33dec60fe83779e7fdc90e955c`
- Исходная версия кода: `1.8.6`
- Python requirement: `>=3.12`
- Alembic head: `0005_plan_outcome_invalid_input`
- Migrations: `0001`–`0005`, один head
- Исходное дерево: 76 production/maintenance files (`app`, `scripts`, `migrations`, `manage.py`), 27 test files, 13 documentation files
- В исходном архиве отсутствовали `CHANGELOG.md` и физический `PATCH_1.8.6.md`, хотя manifest ссылался на patch; `QA_REPORT` заканчивался 1.8.5, а заголовок `SPEC_COMPLIANCE` указывал 1.8.1.

Baseline выполнялся в изолированном virtual environment вне release tree. Первичная попытка в host Python не считалась authoritative из-за отсутствующих project dependencies.

## 2. Цель и критерии приемки

После итерации система должна безопасно повторно проверять немедленную исполнимость и общий риск при operator accept, что подтверждается независимыми unit contracts и полным regression suite.

Критерии:

1. LONG проверяется по ask, SHORT — по bid; fallback на last отсутствует.
2. Missing/stale/future/naive read-only account snapshot не дает подтвержденный капитал.
3. Open risk и effective capital читаются только после глобального transaction-scoped acceptance lock.
4. Stop за оценочной liquidation boundary блокируется при любом плече.
5. Existing advisory-only, PostgreSQL-only и idempotency semantics не ослаблены.
6. Новые тесты проходят отдельно и вместе с полным suite.
7. Версия, config и release documentation синхронизированы.

## 3. Прочитанные источники и data flow

Прочитаны `README.md`, `pyproject.toml`, `.env.example`, `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`, последние iteration reports, production modules и tests. В исходном дереве `CHANGELOG.md` и `PATCH_*.md` отсутствовали.

Изменяемый поток:

`ticker bid/ask + account snapshot + plan/profile` → server-side freshness/geometry validation → global PostgreSQL acceptance lock → open-risk/effective-capital check → `OperatorDecision` + plan status + audit/outbox → API response/manual execution.

Liquidation path:

`entry + SL + leverage` → conservative estimated liquidation distance → buffer/beyond-boundary classification → execution-plan status/warning.

## 4. Baseline до правок

| Команда | Результат |
|---|---|
| `python --version` | Python 3.13.5 |
| `python -m pip check` | PASSED, no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q -rs` | 172 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED, `0005_plan_outcome_invalid_input (head)` |
| `python scripts/release_integrity.py --root <pristine>` | FAILED: 130 files checked, 131 entries; missing `PATCH_1.8.6.md` |
| `python manage.py doctor` | NOT RUN: нет рабочей локальной PostgreSQL/runtime-конфигурации |
| `python manage.py test --require-integration` | NOT RUN: отдельная `TEST_DATABASE_URL` не настроена |

Четыре skip относятся к PostgreSQL integration tests и явно сообщают `TEST_DATABASE_URL is not configured`.

## 5. Подтвержденные дефекты

### D1. Entry-zone проверялась по неисполняемому last price — HIGH, CONFIRMED DEFECT

- Файл: `app/api/v1/recommendations.py`, `accept_recommendation`.
- Было: `entry_low <= ticker.last_price <= entry_high`.
- Контрпример: LONG zone `[100, 101]`, `last=100.5`, `ask=102`. Старый код разрешал принятие, хотя немедленный buy уже вне зоны.
- Влияние: фактический stop distance, net R/R, EV и размер относятся к другой цене, чем доступная для исполнения.
- Почему тесты не ловили: отсутствовал контракт выбора adverse order-book side на accept boundary.

### D2. Устаревший account snapshot считался подтвержденным — HIGH, CONFIRMED DEFECT

- Файл: `app/services/execution.py`, `effective_capital`.
- Было: выбирался последний snapshot без проверки возраста или future/naive timestamp.
- Контрпример: строка equity/available margin старше нескольких циклов sync продолжала давать `verified=True`.
- Влияние: plan и accept могли использовать уже несуществующий капитал или свободную маржу.
- Почему тесты не ловили: тестов age boundary account snapshot не было.

### D3. Race при параллельном принятии общего риска — HIGH, CONFIRMED DEFECT

- Файлы: `app/api/v1/recommendations.py`, `app/services/execution.py`.
- Было: row lock ставился только на выбранный plan; `open_risk_usdt` читался без общего lock.
- Контрпример: при open risk 10 и лимите 20 два плана с risk 6 одновременно видят `10+6<=20`, после обоих commit итог 22.
- Влияние: нарушение `max_total_risk_rate` без ошибки одного из запросов.
- Почему тесты не ловили: проверялся индивидуальный lifecycle, но не глобальная сериализация portfolio invariant.

### D4. Stop за liquidation boundary не блокировался при leverage ≤3 — HIGH, CONFIRMED DEFECT

- Файл: `app/services/execution.py`, post-sizing liquidation check.
- Было: при `buffer < stop_distance` status менялся на `BLOCKED_LIQUIDATION` только если `leverage > 3`.
- Контрпример: entry 100, stop 65, leverage 3; stop distance 35%, estimated boundary 30%, buffer 0. Старый код оставлял план исполнимым с warning.
- Влияние: рассчитанный SL расположен дальше предполагаемой ликвидации и не может выполнять роль ограничителя риска.
- Почему тесты не ловили: не было low-leverage beyond-boundary case.

### D5. Release metadata была рассинхронизирована — MEDIUM, CONFIRMED DEFECT

- Manifest ссылался на отсутствующий patch file; QA/spec headers отставали от кода.
- Влияние: release-check исходного дерева не мог быть достоверным источником состава и версии.
- Исправление ограничено восстановлением release notes и синхронизацией текущего релиза; исторические утверждения не выдумывались.

## 6. План и фактический diff

Production:

- `app/risk/math.py`: независимая liquidation assessment.
- `app/services/execution.py`: executable side helper, snapshot freshness, acceptance state/lock, fail-closed liquidation status.
- `app/api/v1/recommendations.py`: accept revalidation по bid/ask, stale capital block, locked risk state, расширенная diagnostics snapshot.
- `app/config.py`: `MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS` и validator.

Tests:

- `tests/unit/test_execution_acceptance_safety.py`: 12 новых regression/contract tests.

Config/release/docs:

- `.env.example`, `README.md`, `CHANGELOG.md`, `PATCH_1.8.7.md`;
- `docs/ARCHITECTURE.md`, `docs/CONFIGURATION.md`, `docs/OPERATOR_MANUAL.md`, `docs/SECURITY.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- текущий iteration report и regenerated `SHA256SUMS`.

Migration/API compatibility:

- DB migration отсутствует.
- Existing endpoints и response body совместимы; internal decision context расширен.
- Новая env variable имеет safe default.
- Ордерные Bybit endpoints не добавлены.

## 7. Red → green

Red до production implementation:

```text
python -m pytest -q tests/unit/test_execution_acceptance_safety.py
ERROR collecting ...
ImportError: cannot import name 'assess_liquidation_proximity' from 'app.risk.math'
```

Green после implementation:

```text
python -m pytest -q tests/unit/test_execution_acceptance_safety.py
12 passed
```

Тесты независимо проверяют adverse bid/ask side, invalid side fail-closed, stale snapshot cutoff, lock-before-risk ordering, low-leverage liquidation boundary, config minimum и итоговые execution-plan statuses.

## 8. Post-check

| Команда | Baseline 1.8.6 | Post 1.8.7 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q -rs` | 172 passed, 4 skipped | 184 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic heads | one: `0005` | one: `0005` |
| Release integrity | FAILED: missing `PATCH_1.8.6.md` | PASSED after clean manifest regeneration |

Warnings: 19 dependency deprecation warnings from joblib/NumPy in existing runtime tests; новых project warnings не добавлено.

## 9. Непроверенное

- Реальная PostgreSQL concurrency execution двух одновременных HTTP accept-запросов: `TEST_DATABASE_URL` отсутствует.
- `manage.py doctor` против рабочей локальной БД/Bybit account config.
- Реальный latency/freshness профиль Bybit account endpoint; default 180 выбран как три штатных 60-second poll cycles и должен быть подтвержден paper/shadow эксплуатацией.
- Экономическая прибыльность стратегии не проверялась и не следует из технического suite.

## 10. Остаточные риски и ограничения

- `app/ml/features.py` вычисляет EMA по всему symbol history и не сбрасывает state на hourly gap/duplicate. После recovery continuity flag может стать true, но EMA сохраняет затухающий pre-gap вклад. Это подтвержденный econometric gap, не включенный в текущий execution-safety scope.
- Runtime artifact boundary не проверяет каждое `predict_proba` distribution на finite/[0,1]/sum-to-one непосредственно перед policy use. Candidate evaluation имеет проверки, но corrupted/custom runtime model должен блокироваться отдельно.
- Полная liquidation price зависит от exchange maintenance margin tiers и account mode; текущая формула остается консервативной approximation, а не биржевым liquidation calculator.
- Глобальный acceptance lock соответствует текущему глобальному `open_risk_usdt`. При будущем profile/account-scoped risk ledger lock namespace должен меняться вместе с бизнес-инвариантом.

## 11. Rollback

1. Остановить API/worker/trainer.
2. Вернуть файлы release 1.8.6 и его корректный manifest.
3. Удалить `MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS` из локального `.env` необязательно: 1.8.6 игнорирует unknown setting.
4. DB downgrade не требуется.
5. Повторно выполнить compileall/Ruff/pytest/release-check перед запуском.

Rollback возвращает четыре описанных дефекта; использовать его допустимо только для диагностики, не для штатной эксплуатации.

## 12. Следующий рекомендуемый work package

Сегментировать stateful ML features по строго непрерывным hourly runs и сбрасывать EMA/rolling state на gap/duplicate. Добавить regression, где post-gap feature vector совпадает с расчетом на чистом segment-only history, затем проверить train/live parity. Runtime probability-simplex validation следует выполнить отдельной следующей итерацией, чтобы не смешивать два независимых scope.
