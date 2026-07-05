# QA Report — 1.21.0

Date: 2026-07-05
Scope: prospective recommendation UI-exposure ledger and exposure-conditioned operator-selection diagnostics.

## Environment

- Input release: 1.20.0
- Input ZIP SHA-256: `4415ec63775348d8b9cbd45fc5f369529467de95a2b23205322d1f231535501b`
- Checks executed in isolated project environment `/mnt/data/cam_1200_venv`; no production database was used.
- Python: 3.13.5; project requirement remains Python >=3.12.

The global host environment was not used because it lacked project packages (`psycopg`, `ruff`) and contained an unrelated `moviepy`/`pillow` conflict.

## Baseline

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 568 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0013_experiment_preregistration` |

The four skipped tests require a separately configured PostgreSQL integration database.

## Red → green

The new regression module was first executed against untouched 1.20.0 and failed during collection because the exposure ledger contract did not exist:

```text
ImportError: cannot import name 'SelectionExposureLedger' from 'app.db.models'
```

After implementation, fourteen focused tests passed. They cover evidence hashing and tamper detection, temporal/viewport/dwell validation, exposed-only selection cohorts, low-coverage blocking, prospective rollout semantics, corrupted ledger handling, ORM/migration immutability, configuration bounds, endpoint authentication/idempotency contracts and frontend visible-dwell instrumentation.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests migrations manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 582 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

## Not run / unavailable

- `python manage.py test --require-integration`: NOT RUN because no isolated `TEST_DATABASE_URL` was supplied.
- PostgreSQL migration upgrade/downgrade: NOT RUN against a live PostgreSQL instance. Migration structure, constraints, immutability trigger and Alembic graph were checked statically.
- `python manage.py doctor`: NOT RUN from the release tree because it intentionally contains no local `.venv`; equivalent dependency, static, syntax and migration-head checks were run in the isolated environment.
- A real browser/API/PostgreSQL end-to-end exposure stream was not executed because no configured application database and operator session were supplied.
- No profitability, causal operator-skill or model-promotion claim is made.

## Residual warnings

The 61 warnings are existing NumPy/joblib/pandas deprecations. No new warning class was introduced by this iteration.

## Release verification

- Clean staged tree: `227` eligible files; `SHA256SUMS` verified `227/227` before archive creation.
- Staged tree passed dependency check, compileall, Ruff, full pytest (`582 passed, 4 skipped`), frontend syntax and Alembic head `0014_ui_exposure_ledger`.
- Forbidden cache, credential, model-artifact, database-dump and runtime-report files were excluded.
- Advisory-only Bybit-client scan, secret-pattern scan and trailing-whitespace scan: PASSED.
- Preliminary archive contained one root directory `cost_aware_momentum-1.21.0` and passed `unzip -t`.
- Fresh extraction passed release integrity `227/227`, dependency check, compileall, Ruff, full pytest (`582 passed, 4 skipped`), frontend syntax and Alembic head `0014_ui_exposure_ledger`.
- Generated test caches in the verification directory are not copied back into the final release.
- Final ZIP SHA-256 is recorded in the delivery response; it is not embedded inside the archive.
