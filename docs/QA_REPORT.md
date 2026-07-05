# QA Report — 1.23.0

Date: 2026-07-05
Scope: maturity-aware delayed-label correction for production calibration drift.

## Environment

- Input release: `1.22.0`.
- Input ZIP: `cost_aware_momentum-1.22.0-point-in-time-funding-intervals(1).zip`.
- Input ZIP SHA-256: `2fe0014423317a3bd005496b584257926050ae1581b12953f648e89166443a4f`.
- Checks executed in isolated environment `/mnt/data/cam_1210_venv`; no production database was used.
- Python: `3.13.5`; project requirement remains Python `>=3.12`.
- Input archive inventory: one root, 230 files, 93 production files under `app/scripts/web`, 73 Python test files, 23 documentation files and 14 Alembic migrations. No released cache, `.env`, credential, model artifact or database dump was present.

## Baseline before changes

| Check | Result |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `586 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

The four skipped tests require a separately configured PostgreSQL integration database.

## Confirmed defect and red evidence

`app/services/drift_monitor.py::build_production_drift_report` joined every already-resolved `SignalOutcome` in the monitoring window. TP/SL can resolve before the signal horizon ends, but TIMEOUT cannot exist until full maturity. The resulting calibration cohort was right-censored toward early barrier hits.

The new regression module was run before production changes:

```text
2 failed
assert 2 == 1
AssertionError: assert 'CRITICAL' == 'BLOCKED'
```

The first failure proves that an immature early TP was incorrectly included alongside one mature outcome. The second proves that an unresolved mature signal did not fail closed.

## Post-change focused verification

```text
10 passed
```

This includes:

- excluding an early resolved outcome until its full horizon matures;
- publishing mature/resolved/unresolved/excluded maturity coverage;
- blocking calibration when a mature signal lacks an outcome;
- preserving existing PSI, calibration, coverage, heartbeat and directional-probability regressions.

## Post-change full verification

| Check | Result |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `588 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

## Release assertions

- Version sources: `app/__init__.py` and `pyproject.toml` both report `1.23.0`.
- Drift report schema: `production-drift-report-v2`.
- Outcome maturity cohort: `full-horizon-mature-signal-outcomes-v1`.
- No migration or `.env` change.
- No artifact schema or retraining requirement.
- No Bybit order creation/amend/cancel method added.
- `automatic_model_action` remains `none`.

## Not run

- `python manage.py test --require-integration`: NOT RUN because no isolated `TEST_DATABASE_URL` was supplied.
- Live PostgreSQL outcome-resolution/drift-report smoke test: NOT RUN.
- Live Bybit calls: NOT RUN; this patch does not change the Bybit client.
- Profitability or forward-edge validation: NOT RUN and not claimed.

## Release archive verification

- Staged root: `cost_aware_momentum-1.23.0`.
- 233 files including `SHA256SUMS`; 232 checksum entries.
- Staged full suite repeated successfully: `588 passed, 4 skipped, 61 warnings`.
- Cache/build/credential/model/database artifacts are excluded from the release.
- Final ZIP is verified with `unzip -t`, fresh extraction and checksum validation.
