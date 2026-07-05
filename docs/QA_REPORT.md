# QA Report — 1.20.0

Date: 2026-07-05
Scope: immutable formal preregistration of research experiment families before the first trial.

## Environment

- Input release: 1.19.0
- Input ZIP SHA-256: `b95b220814ba41f3c378b6a6478643d88e74209449c59594fe7f6edd1fbcba03`
- Checks executed in isolated project environment `/mnt/data/cam_1190_venv`; no production database was used.
- Python: 3.13.5; project requirement remains Python >=3.12.

## Baseline

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 559 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0012_experiment_selection` |

The four skipped tests require a separately configured PostgreSQL integration database.

## Red → green

The new regression module was first executed against untouched 1.19.0 and failed during collection with:

```text
ModuleNotFoundError: No module named 'app.research.preregistration'
```

After implementation, nine focused tests passed. They cover formal specification normalization, placeholders, exact fixed/search configuration contracts, enumerated values, stopping deadline/budget, record-hash mutation detection, pre-evaluation template generation, STARTED-event preregistration binding, report policy mismatch and the immutable migration/model contract.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests migrations manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 568 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0013_experiment_preregistration` |

## Not run / unavailable

- `python manage.py test --require-integration`: NOT RUN because no isolated `TEST_DATABASE_URL` was supplied.
- PostgreSQL migration upgrade/downgrade: NOT RUN against a live PostgreSQL instance. Migration structure and Alembic graph were checked statically.
- `python manage.py doctor`: NOT RUN because the release tree intentionally does not contain a local `.venv`; equivalent dependency, static, syntax and migration-head checks were run in the isolated environment.
- A real preregistration/backtest family was not created because no project PostgreSQL database, production dataset or model artifact was supplied.
- No profitability, model-promotion or causal claim is made.

## Residual warnings

The 61 warnings are existing NumPy/joblib/pandas deprecations. No new warning class was introduced by this iteration.

## Release verification

- Clean staged tree: `222` eligible files; `SHA256SUMS` verified `222/222` before ZIP creation.
- Preliminary archive contained one root directory `cost_aware_momentum-1.20.0` and passed `unzip -t`.
- Fresh extraction passed release integrity `222/222`, dependency check, compileall, Ruff, full pytest (`568 passed, 4 skipped`), frontend syntax and Alembic head `0013_experiment_preregistration`.
- Generated test caches were not copied back into the release tree.
- Final ZIP SHA-256 is recorded in the delivery response; it is not embedded inside the archive.
