# Iteration report — migration revision compatibility

## 1. Вход

- Архив: `cost_aware_momentum-1.8.30-outcome-integrity.zip`
- SHA-256: `26733e09c55cc2a1e1117b651e555f5328e79740963d52b2f5db6781342008c1`
- Исходная версия: `1.8.30`
- Сообщённое воспроизведение: PostgreSQL `StringDataRightTruncation` при обновлении `alembic_version.version_num`.

## 2. Цель и критерии приемки

После итерации migration 0008 должна применяться через стандартную Alembic version table без изменения её схемы, что подтверждается:

1. длиной каждого revision ID не более 32 символов;
2. единственным head `0008_outcome_path_unavailable`;
3. regression test red → green;
4. корректной offline PostgreSQL SQL-генерацией;
5. отсутствием регрессии полного test suite и static checks;
6. синхронизацией operator/release документации.

## 3. Подтверждённый дефект

**Severity: HIGH — CONFIRMED DEFECT.**

- Файл: `migrations/versions/0008_plan_outcome_path_unavailable.py` в 1.8.30.
- Фактический revision ID: `0008_plan_outcome_path_unavailable`.
- Длина: 34 символа.
- Ограничение реальной БД: `alembic_version.version_num VARCHAR(32)`.
- Фактическое поведение: migration падает на финальном `UPDATE alembic_version`.
- Влияние: release 1.8.30 невозможно штатно развернуть на стандартной PostgreSQL/Alembic схеме; процессы должны оставаться остановленными из-за migration mismatch.
- Почему тесты не поймали: PostgreSQL integration suite не запускалась без отдельной БД, а статического контракта на длину revision ID не существовало.

## 4. Red → green

### Red

`python -m pytest -q tests/unit/test_migration_revision_contract.py` на неизменённом revision ID:

- `1 failed`;
- обнаружено `{'0008_plan_outcome_path_unavailable': 34}`.

### Green

После переименования revision в `0008_outcome_path_unavailable`:

- targeted test: `1 passed`;
- новый ID имеет 29 символов;
- `python -m alembic heads`: single head `0008_outcome_path_unavailable`.

## 5. Изменения

### Production/migration

- `migrations/versions/0008_outcome_path_unavailable.py` — короткий revision ID; migration SQL и backfill не менялись.
- `app/__init__.py`, `pyproject.toml` — версия `1.8.31`.

### Tests

- `tests/unit/test_migration_revision_contract.py` — новый 32-character contract.
- `tests/integration_postgres/test_migrations_and_audit.py` — expected head исправлен с устаревшего `0007` на `0008_outcome_path_unavailable`.

### Docs/release

- `README.md`, `CHANGELOG.md`, `PATCH_1.8.31.md`.
- `docs/CONFIGURATION.md`, `docs/OPERATOR_MANUAL.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/SECURITY.md`.
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`.
- 1.8.30 patch/report помечены как superseded/withdrawn.

## 6. SQL и транзакционность

Offline SQL generation для PostgreSQL показывает transactional DDL и финальную команду:

```sql
UPDATE alembic_version
SET version_num='0008_outcome_path_unavailable'
WHERE alembic_version.version_num = '0007_position_account_scope';
```

Тело migration сохраняет прежний fail-closed backfill. После типичного падения 1.8.30 ожидается полный rollback до revision 0007. Ручное расширение version table или `stamp` не требуется и не рекомендуется.

## 7. Post-check

- `python -m pip check` — PASSED, no broken requirements в isolated venv.
- `python -m compileall -q app scripts tests manage.py migrations` — PASSED.
- `python -m ruff check .` — PASSED.
- `python -m pytest -q` — PASSED: 408 passed, 4 skipped, 19 warnings.
- `node --check web/js/app.js` — PASSED.
- `python -m alembic heads` — PASSED: one head `0008_outcome_path_unavailable`.
- Offline PostgreSQL migration SQL generation — PASSED.

## 8. Непроверенное

- Реальный upgrade/backfill/downgrade на отдельной PostgreSQL не запускался: `TEST_DATABASE_URL` и безопасная test DB отсутствовали.
- Четыре integration tests поэтому skipped.
- Базы, которые были вручную widened/stamped старым 34-символьным revision ID, не тестировались и требуют отдельной remediation.

## 9. Rollback

До применения 0008: вернуть код 1.8.29/1.8.30 нельзя рекомендовать из-за известного migration defect; используйте 1.8.31.

После успешного применения 0008 штатный downgrade остаётся fail-closed при наличии `PATH_UNAVAILABLE` rows. Сначала требуется осознанная data remediation на backup/test copy, затем Alembic downgrade.

## 10. Следующий work package

Запустить весь migration chain, backfill и controlled downgrade на отдельном PostgreSQL clone с репрезентативными `plan_outcomes`, включая malformed `planning_time` и крупный объём строк.
