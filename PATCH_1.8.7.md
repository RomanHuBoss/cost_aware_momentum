# Patch 1.8.7 — fail-closed execution acceptance

## Проблема

В принятии рекомендаций оставались четыре связанные ошибки:

1. зона входа повторно проверялась по `last_price`, хотя немедленный LONG исполняется по ask, а SHORT — по bid;
2. последний account equity snapshot считался подтвержденным независимо от возраста;
3. два параллельных accept-запроса могли одновременно прочитать один и тот же свободный portfolio-risk budget;
4. stop-loss за оценочной liquidation boundary при плече 1–3x давал только warning.

## Решение

- Введен `executable_entry_price`: ask для LONG, bid для SHORT, invalid/missing side fail-closed.
- `effective_capital` проверяет возраст, timezone и future timestamp read-only snapshot.
- `load_acceptance_risk_state` захватывает глобальный PostgreSQL transaction advisory lock до чтения open risk и effective capital.
- Вынесена независимая `assess_liquidation_proximity`; stop beyond estimated boundary всегда блокируется.
- Decision context сохраняет executable, last, bid, ask и capital snapshot diagnostics.

## Конфигурация

```env
MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS=180
```

Минимум — 30 секунд. Значение должно быть согласовано с периодом account sync и эксплуатационной задержкой. При отсутствии переменной используется default 180.

## Миграции и совместимость

- Alembic migration не требуется.
- API response schema не ломается; `context_snapshot` расширен диагностическими полями.
- Advisory-only boundary сохранена: accept не размещает ордер.
- Existing model artifacts и DB rows совместимы.

## Проверки

- red: новый test module не собирался, потому что `assess_liquidation_proximity` отсутствовала;
- green: `12 passed` в `tests/unit/test_execution_acceptance_safety.py`;
- full suite: `184 passed, 4 skipped`;
- compileall, Ruff, Node syntax и Alembic head: passed.
- исходный release integrity defect (`PATCH_1.8.6.md` missing) устранен regenerated clean manifest.

PostgreSQL integration tests не запускались без отдельной `TEST_DATABASE_URL`; конкурентная семантика lock подтверждена unit-контрактом и использованием штатного `pg_advisory_xact_lock`, но требует отдельного DB concurrency smoke test.
