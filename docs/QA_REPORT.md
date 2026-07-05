# QA Report — 1.18.0

Date: 2026-07-05
Scope: prospective research experiment ledger, CSCV/PBO and Deflated Sharpe governance.

## Environment

- Input release: 1.17.0
- Input ZIP SHA-256: `9c779cac82da74377c6d428dd76346c3d52946bcc15aca56af5844d9f322773c`
- Checks executed in isolated project environment `/mnt/data/cam_venv_115`; no production database was used.
- Python: 3.13.5 (project requirement remains Python >=3.12).

## Baseline

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 540 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0011_selection_experiment` |

The four skipped tests require a separately configured PostgreSQL integration database.

## Red → green

The new regression module was first executed against untouched 1.17.0 and failed during collection with:

```text
ModuleNotFoundError: No module named 'app.research.overfitting'
```

After implementation, the focused experiment-governance tests passed. They independently cover stable/regime-reversing PBO, DSR formula, correlation-adjusted trial count, disclosure blocking, duplicate configuration handling, hash tampering, aligned hourly return evidence, schema constraints and configuration validation.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 550 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0012_experiment_selection` |

## Not run / unavailable

- `python manage.py test --require-integration`: NOT RUN because no isolated `TEST_DATABASE_URL` was supplied.
- Migration upgrade/downgrade against PostgreSQL: NOT RUN for the same reason.
- `python manage.py doctor`: NOT RUN because the release tree intentionally has no local `.venv`; equivalent static/dependency/head checks were run in the isolated environment.
- Live backtest family with production history: NOT RUN; no profitability or PBO/DSR result is claimed.

## Residual warnings

The 61 warnings are existing NumPy/joblib/pandas deprecations. No new warning class was introduced by this iteration.

## Release verification

- Clean staged tree: 211 eligible files; `SHA256SUMS` verified 211/211.
- ZIP structure: one root directory `cost_aware_momentum-1.18.0`; `unzip -t` passed.
- Fresh extraction: release integrity 211/211, dependency check, compileall, Ruff, full pytest (`550 passed, 4 skipped`), frontend syntax and Alembic head all passed.
- Forbidden cache, credential, model-artifact, dump and generated-report files are absent from the final tree.
