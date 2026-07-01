# QA Report — 1.8.25

Дата: 2026-07-01

## Baseline 1.8.24

Изолированное окружение `/mnt/data/cam_venv`:

| Проверка | Результат |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 363 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | NOT RUN in project-managed environment; входной архив не содержал `.venv`/`.env` |
| `python manage.py test --require-integration` | NOT RUN; отдельная безопасная PostgreSQL test database отсутствовала |

Глобальный Python environment не использован как доказательство baseline: в нём были unrelated dependency conflicts и отсутствовал `psycopg`.

## Post-check 1.8.25

| Проверка | Результат |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 371 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| Independent Decimal economics audit | 10 000 cases PASSED |
| Independent barrier parity audit | 5 000 cases PASSED |
| PostgreSQL integration suite | NOT RUN |

`python scripts/release_integrity.py --root . --write`: PASSED, 148 files checked and listed. Final archive test and ZIP SHA-256 are reported to the user after packaging.
