# QA Report — 1.8.31

Дата: 2026-07-02

## Вход и инцидент

- Входной release: `cost_aware_momentum-1.8.30-outcome-integrity.zip`.
- SHA-256: `26733e09c55cc2a1e1117b651e555f5328e79740963d52b2f5db6781342008c1`.
- Пользователь воспроизвёл PostgreSQL migration failure: `StringDataRightTruncation` при попытке записать `0008_plan_outcome_path_unavailable` в `alembic_version.version_num VARCHAR(32)`.
- Revision ID 1.8.30 имел 34 символа. Release 1.8.30 признан неразвёртываемым на стандартной Alembic version table и заменён 1.8.31.

## Доказательство red → green

| Этап | Команда | Результат |
|---|---|---|
| Red на revision 1.8.30 | `python -m pytest -q tests/unit/test_migration_revision_contract.py` | FAILED — `{'0008_plan_outcome_path_unavailable': 34}` |
| Green после исправления | та же команда | PASSED — 1 test |
| Alembic graph | `python -m alembic heads` | PASSED — single head `0008_outcome_path_unavailable` |
| Release tree + `SHA256SUMS` | PASSED — 159 files checked, 159 manifest entries |
| Offline PostgreSQL SQL | `python -m alembic upgrade 0007_position_account_scope:0008_outcome_path_unavailable --sql` | PASSED — final version update uses 29-character ID |

## Post-check в isolated venv

| Проверка | Статус и результат |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py migrations` | PASSED |
| `python -m ruff check .` | PASSED — all checks passed |
| `python -m pytest -q` | PASSED — 408 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — single head `0008_outcome_path_unavailable` |
| PostgreSQL integration suite | SKIPPED — 4 tests; `TEST_DATABASE_URL` not configured |
| Real migration upgrade/backfill/downgrade | NOT RUN — safe PostgreSQL test database unavailable |

Глобальный Python environment отдельно имел посторонний MoviePy/Pillow conflict. Он не использован как QA evidence; все project checks выполнены в чистом venv с `-e .[dev]`.

## Исправленные файлы

- `migrations/versions/0008_outcome_path_unavailable.py`.
- `tests/unit/test_migration_revision_contract.py`.
- `tests/integration_postgres/test_migrations_and_audit.py`.
- `app/__init__.py`, `pyproject.toml`.
- Release/operator/QA документация и manifest.

## Compatibility и действия оператора

- Новых зависимостей, env-переменных, API fields или trading semantics нет.
- После неудачного upgrade 1.8.30 не расширять `alembic_version` и не делать `stamp`.
- Проверить `python -m alembic current`; ожидается `0007_position_account_scope`.
- Установить 1.8.31 и выполнить `python manage.py migrate`.
- Итоговый head: `0008_outcome_path_unavailable`.

## Остаточные риски

- Upgrade/backfill не выполнен на реальной PostgreSQL copy.
- Если version table была вручную расширена или база stamped старым 34-character ID, автоматическое восстановление не подтверждено.
- Экономическая прибыльность стратегии этой итерацией не оценивалась.
