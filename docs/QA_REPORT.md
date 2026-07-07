# QA Report — 1.51.1

Дата проверки: 2026-07-07.

## Окружение

- Python: 3.13.5.
- Project Python requirement: `>=3.12`.
- Alembic head: `0018_inference_observations`.
- Проверки выполнялись в отдельном virtual environment `/mnt/data/cam_work/venv`; project-local `.venv` не создавался.

## Baseline до production-правок

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 836 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py release-check` | FAILED | manifest отсутствовал; после baseline также обнаружены сгенерированные caches/egg-info |
| `python manage.py doctor` | NOT RUN | baseline запускался в external venv без project-local `.venv` и рабочей DB-конфигурации |
| `python manage.py test --require-integration` | NOT RUN | отдельная безопасная `TEST_DATABASE_URL` не была настроена |

До запуска тестов inventory входного ZIP отдельно подтвердил отсутствие `SHA256SUMS`, `CHANGELOG.md`, `PATCH_*.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md` и `docs/TRACEABILITY.md`.

## Red → green

Команда:

```bash
python -m pytest -q \
  tests/unit/test_release_contract_2026_07_07.py \
  tests/unit/test_release_integrity.py
```

- Red на исходном production code: 2 failed. `verify_release_tree()` возвращал `ok=True` для неполного tree и для version drift.
- Green после исправления: 5 passed.

## Post-check

| Проверка | Статус | Результат |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 838 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED | ожидает project-local `.venv`; external venv не распознан |
| `python manage.py test --require-integration` | NOT RUN | отдельная безопасная PostgreSQL test DB отсутствовала |
| `python -B manage.py release-check --write` | PASSED | manifest создан после очистки release tree |
| `python -B manage.py release-check` | PASSED | полный contract, version markers и checksums проверены |
| ZIP integrity / clean re-extract | PASSED | итоговый архив протестирован и повторно распакован |

## Warnings

62 существующих `DeprecationWarning` связаны преимущественно с pandas/NumPy timedelta semantics. Они не стали failures, но требуют отдельной совместимой cleanup-итерации до обновления зависимостей, где warning станет error.

## Scope statement

В 1.51.1 изменён только release/security governance layer. Risk math, signal selection, ML training, database schema и API contracts не менялись. Проверка технической целостности не является доказательством прибыльности стратегии.
