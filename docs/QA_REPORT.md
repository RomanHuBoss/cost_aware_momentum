# QA report — 1.52.22

Date: 2026-07-09  
Scope: `frontend-data-list-escaping`

## Baseline before code changes

| Command | Status | Exact result / note |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 8.88s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Red evidence

The new regression was added before changing `web/js/app.js`.

Command:

```bash
python -m pytest -q tests/unit/test_frontend_html_escaping_2026_07_09.py
```

Result on unpatched 1.52.21 code:

```text
FAILED tests/unit/test_frontend_html_escaping_2026_07_09.py::test_data_list_escapes_labels_and_values_before_inner_html_insertion - AssertionError: assert 'function formatDataListValue' in ...
1 failed in 0.16s
```

This proved that the shared detail-list renderer had no central value formatter and still used raw label/value interpolation before `innerHTML` insertion.

## Green evidence

New regression:

```bash
python -m pytest -q tests/unit/test_frontend_html_escaping_2026_07_09.py
```

```text
1 passed in 0.08s
```

Related UI subset:

```bash
python -m pytest -q tests/unit/test_frontend_html_escaping_2026_07_09.py tests/unit/test_trainer_operator_ui.py
```

```text
3 passed in 0.09s
```

## Post-check after code and documentation updates

| Command | Status | Exact result / note |
|---|---:|---|
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit code 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 7.05s`; representative error `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit code 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| Targeted new regression | PASSED | `1 passed in 0.07s` |
| Related UI subset | PASSED | `3 passed in 0.10s` |
| Forbidden exchange write endpoint grep in `app scripts web` | PASSED | no create/amend/cancel/withdraw exchange endpoint implementation found |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 293 files checked, 293 manifest entries.` after cache cleanup |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 293 files checked, 293 manifest entries.` |
| `python manage.py doctor` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |
| `python manage.py test --require-integration` | SKIPPED | no safe configured PostgreSQL instance in sandbox and `psycopg` missing |

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## Unverified in this sandbox

- Full pytest collection and PostgreSQL integration tests require installed `psycopg` and a safe PostgreSQL test database.
- `ruff` static analysis requires the missing `ruff` package.
- `pip check` remains blocked by an unrelated sandbox-level `moviepy`/`pillow` dependency conflict.
- Real Bybit paper/shadow/forward evidence was not run.
