# QA report

Дата проверки версии 1.6.0: 28 июня 2026 г.

## Baseline до изменений

Проверки выполнены на исходном архиве `cost_aware_momentum-main(3).zip` в изолированном Python environment:

| Проверка | Результат |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — broken requirements не обнаружены |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 54 passed, 2 skipped, 20 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | NOT RUN — baseline wrapper не нашел project-local `.venv` |
| `python manage.py test --require-integration` | NOT RUN — baseline wrapper не нашел project-local `.venv`; отдельная PostgreSQL test database отсутствовала |

Baseline содержал 2 skipped PostgreSQL integration tests. После добавления нового outcome integration test post-check содержит 3 skipped integration tests; все требуют отдельную PostgreSQL test database.

## Post-check версии 1.6.0

| Проверка | Результат |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 67 passed, 3 skipped, 20 warnings |
| `python -m pytest -q tests/unit/test_counterfactual_outcomes.py` | PASSED — 12 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — единственный head `0004_counterfactual_outcomes` |
| `git diff --check` | PASSED |
| `python manage.py doctor` | FAILED (environment) — нет `.env`, замененных secrets, PostgreSQL service и native tools |
| `python manage.py test --require-integration` | UNAVAILABLE — не заданы `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` |
| Версия пакета / приложения | `1.6.0` / `1.6.0` |

## Red → green evidence

До production implementation новый acceptance module был запущен отдельно:

```text
python -m pytest -q tests/unit/test_counterfactual_outcomes.py
```

RED: collection завершилась ошибкой `ModuleNotFoundError: No module named 'app.services.outcomes'`.

После реализации тот же module прошел: `12 passed`.

## Проверенный контракт counterfactual outcome

Unit tests и static analysis подтверждают:

1. LONG и SHORT используют правильную направленную геометрию;
2. TP1/SL разрешаются только по confirmed contiguous hourly path;
3. same-bar TP1+SL дает conservative `SL` и `ambiguous=true`;
4. TIMEOUT не создается до точного confirmed horizon close;
5. пропуск первой или промежуточной свечи оставляет outcome pending;
6. invalid prices/directional geometry fail closed;
7. plan costs используют immutable execution-plan snapshot;
8. входная и выходная fee legs считаются от соответствующих executed notionals;
9. stop-gap reserve применяется только к SL;
10. funding scenario включает только settlement timestamps до outcome exit;
11. legacy plan без funding timeline помечается `FUNDING_UNAVAILABLE`, R не выдумывается;
12. qty=0 помечается `NOT_SIZED`, R не выдумывается;
13. signal/plan uniqueness и transaction advisory lock защищают идемпотентность;
14. audit и outbox создаются в той же транзакции;
15. detail API и UI различают counterfactual estimate и actual manual P&L.

## PostgreSQL integration tests

В среде сборки отсутствовали `postgres`, `psql`, `initdb`, `pg_dump`, `pg_restore` и отдельная test database. Поэтому migration 0004 не проверялась фактическим upgrade/downgrade на PostgreSQL; 3 integration tests остались skipped.

Перед эксплуатацией выполните на отдельной базе:

```powershell
$env:POSTGRES_ADMIN_URL="postgresql+psycopg://postgres:ПАРОЛЬ@localhost:5432/postgres"
py -3.12 manage.py test --require-integration
Remove-Item Env:POSTGRES_ADMIN_URL
```

Затем отдельно проверьте:

1. upgrade существующей схемы 0003 → 0004;
2. clean install до head;
3. unique constraints при двух конкурентных worker attempts;
4. outcome resolution после подтвержденных candles;
5. backfill новой execution-plan version после уже разрешенного signal outcome;
6. API detail и SSE refresh на локальном UI;
7. downgrade только на disposable database.

## Release boundary

Проверено статически:

- Bybit client не содержит order create/amend/cancel методов;
- advisory-only boundary не изменена;
- PostgreSQL остается единственной СУБД;
- bind default остается `127.0.0.1`;
- `.env`, credentials, model artifacts, caches, `.git`, `.venv`, `*.egg-info` и stale `SHA256SUMS` не должны входить в release ZIP.

## Не покрыто данной проверкой

- фактический PostgreSQL migration/integration run;
- длительный worker smoke-test на реальном потоке Bybit;
- 1–5-минутное восстановление порядка TP/SL;
- partial TP1/TP2, no-fill, operator latency и historical orderbook impact;
- сравнение estimated counterfactual P&L с фактическими fills;
- paper/shadow forward evidence и экономическое преимущество стратегии.

## Release recheck

Финальные counts, SHA-256 ZIP и результат повторной распаковки зафиксированы в `docs/ITERATION_REPORT_2026-06-28_counterfactual-outcomes.md` после упаковки.
