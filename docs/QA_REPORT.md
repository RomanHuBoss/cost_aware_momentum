# QA Report — 1.24.0

Date: 2026-07-05
Scope: prospective fail-closed candidate/live recommendation attrition diagnostics.

## Environment

- Input release: `1.23.0`.
- Input ZIP: `cost_aware_momentum-1.23.0-maturity-aware-drift-calibration(1).zip`.
- Input ZIP SHA-256: `249a9f1023741134d4d65d5bb6f6b982b5f6c666aaba5d6ec0511df0cff43a18`.
- Checks executed in isolated environment `/mnt/data/cam_124_venv`; no production database was used.
- Python: `3.13.5`; project requirement remains Python `>=3.12`.
- Input archive inventory: one root, 233 files, 93 production files under `app/scripts/web`, 74 test files, 24 documentation files and 14 Alembic migrations. No released cache, `.env`, credential, model artifact or database dump was present.

The host Python environment was not used as the authority because it lacked project dependencies and contained an unrelated Pillow/MoviePy dependency conflict. A fresh isolated environment was used for all authoritative checks.

## Baseline before changes

| Check | Result |
|---|---|
| `python -m pip check` | PASSED — no broken requirements in isolated environment |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `588 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

The four skipped tests require a separately configured PostgreSQL integration database.

## Confirmed gap and red evidence

`app/services/signals.py::publish_hourly_signals` previously exposed only aggregate `skip_counts`, `published` and `plan_status_counts`. It did not persist one terminal record per symbol, so repeated hourly/catch-up attempts could not be deduplicated by opportunity. `app/services/execution.py::create_execution_plan` did not persist one stable machine-readable primary attrition cause, and no service combined training quality-gate/activation outcomes with live signal/plan attrition.

New tests were executed before production implementation:

```text
KeyError: 'attrition_schema'
ModuleNotFoundError: No module named 'app.services.attrition'
```

These failures independently demonstrated the absence of per-symbol terminal instrumentation and the aggregate report contract.

## Post-change focused verification

The two new modules and related execution-plan regressions passed:

```text
4 passed
48 passed
```

Coverage includes:

- exactly one terminal outcome for every selected inference symbol;
- retry deduplication by `symbol × event_time` and explicit recovery count;
- machine-readable initial-plan primary/contributing causes;
- candidate gate/activation aggregation;
- fail-closed incomplete denominator evidence;
- preservation of existing execution safety contracts.

## Post-change full verification

| Check | Result |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `592 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

## Release assertions

- Version sources: `app/__init__.py` and `pyproject.toml` report `1.24.0`.
- Inference schema: `hourly-inference-terminal-outcomes-v1`.
- Plan evidence schema: `execution-plan-attrition-v1`.
- Aggregate schema: `candidate-live-attrition-report-v1`.
- No migration, `.env`, model artifact or threshold change.
- No Bybit order creation/amend/cancel method added.
- Report is diagnostic only and has no automatic model or policy action.

## Not run

- `python manage.py doctor`: NOT RUN as an authoritative check because the clean release intentionally contains no project-local `.venv`; equivalent dependency, import, version and migration-head checks passed in the isolated environment.
- `python manage.py test --require-integration`: NOT RUN because no isolated `TEST_DATABASE_URL` was supplied.
- Live PostgreSQL attrition-report smoke test: NOT RUN.
- Live Bybit calls: NOT RUN; the Bybit client was not changed.
- Forward profitability or causal value-of-lost-opportunity analysis: NOT RUN and not claimed.

## Release archive verification

- Staged root: `cost_aware_momentum-1.24.0`.
- 238 files including `SHA256SUMS`; 237 checksum entries.
- Staged full suite repeated successfully: `592 passed, 4 skipped, 61 warnings`.
- Cache/build/credential/model/database artifacts are excluded.
- ZIP is tested with `unzip -t`, fresh extraction and `sha256sum -c SHA256SUMS`.
