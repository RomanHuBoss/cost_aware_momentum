# QA Report — 1.19.0

Date: 2026-07-05
Scope: dependence-aware inference for experiment-overfitting and operator-selection reports.

## Environment

- Input release: 1.18.0
- Input ZIP SHA-256: `605887261acc2b38e88a31f6ff2d06a84ca7902e9028c1482328f1721f0d6e9c`
- Checks executed in isolated project environment `/mnt/data/cam_venv_115`; no production database was used.
- Python: 3.13.5 (project requirement remains Python >=3.12).

## Baseline

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 550 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0012_experiment_selection` |

The four skipped tests require a separately configured PostgreSQL integration database.

## Red → green

The new regression module was first executed against untouched 1.18.0 and failed during collection with:

```text
ModuleNotFoundError: No module named 'app.research.dependence'
```

After implementation, nine focused tests passed. They independently cover Bartlett/Newey–West arithmetic, deterministic moving-block bootstrap, HAC-adjusted DSR, minimum independent blocks, horizon-floor enforcement, mixed-horizon blocking, atomic signal-cluster propensity splits, signal-cluster bootstrap intervals, service cluster mapping and fail-closed configuration.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 559 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0012_experiment_selection` |

## Not run / unavailable

- `python manage.py test --require-integration`: NOT RUN because no isolated `TEST_DATABASE_URL` was supplied.
- PostgreSQL migration upgrade/downgrade: NOT RUN; this release adds no migration and the database head remains unchanged.
- `python manage.py doctor`: NOT RUN because the release tree intentionally has no local `.venv`; equivalent dependency, static, syntax and migration-head checks were run in the isolated environment.
- Production experiment or operator-selection evidence: NOT RUN; no profitability, causal operator-skill or live-edge conclusion is claimed.

## Residual warnings

The 61 warnings are existing NumPy/joblib/pandas deprecations. No new warning class was introduced by this iteration.

## Release verification

- Clean staged tree: `215` eligible files; `SHA256SUMS` verified `215/215`.
- ZIP structure: one root directory `cost_aware_momentum-1.19.0`; `unzip -t` passed.
- Fresh extraction: release integrity `215/215`, dependency check, compileall, Ruff, full pytest (`559 passed, 4 skipped`), frontend syntax and Alembic head all passed.
- Forbidden cache, credential, model-artifact, dump and generated runtime-report files are absent from the final tree.
