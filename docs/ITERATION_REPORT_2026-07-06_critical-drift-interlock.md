# Iteration report — critical production-drift publication interlock

## 1. Input and identification

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `d5e3e857ef4adb0e946a4ba3b3aacdf379b493fa1c0b03566ef3ebdfc0957436`
- Source release: 1.26.7; target release: 1.27.0
- Python requirement: >=3.12; tested with 3.13.5
- Inventory before changes: 225 files; 94 production Python, 83 test Python, 10 docs; 14 Alembic revisions; single head `0014_ui_exposure_ledger`
- Input release contained no `.env`, credentials, virtual environment, model artifact or database dump. Generated caches/egg-info are excluded from the output.

## 2. Goal and acceptance criteria

After this iteration, a confirmed `CRITICAL` production-drift report must fail closed for the exact active model version before another hourly advisory decision is published, and the quarantine must also prevent creation or acceptance of actionable execution plans.

Acceptance criteria:

1. Persisted current-version `CRITICAL` evidence latches across restart and later non-critical diagnostic reports.
2. Evidence for a previous version does not quarantine a newly activated version.
3. Runtime/signal version must match current active registry; disabling new monitor jobs or reactivating the same immutable version cannot clear a persisted latch.
4. Hourly drift executes before inference.
5. New signals are not published while quarantined and diagnostics identify every skipped symbol.
6. New/recalculated plans are `NO_TRADE` with explicit guard evidence.
7. Previously actionable plans cannot be accepted after quarantine.
8. Insufficient warm-up `BLOCKED` evidence does not create a self-sustaining publication deadlock.
9. Advisory-only, PostgreSQL-only, model gates and recommendation thresholds remain unchanged.

## 3. Sources and data flow

Read: `README.md`, `CHANGELOG.md`, patches 1.26.5–1.26.7, `pyproject.toml`, `.env.example`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, embedded DOCX specification, and relevant drift/worker/signal/execution/acceptance modules and tests. The repository does not contain several generic architecture/security/operator documents named in the iteration prompt; they were not invented.

Changed flow:

`mature SignalOutcome evidence + immutable active-model reference` → production drift report → successful persisted `JobRun` → exact-version quarantine guard → hourly pre-inference signal short-circuit → central execution-plan `NO_TRADE` → acceptance recheck/recalculation conflict.

## 4. Baseline

Isolated environment `/mnt/data/cam_venv`:

- `python --version`: PASSED, 3.13.5
- `python -m pip check`: PASSED
- `python -m compileall -q app scripts tests manage.py`: PASSED
- `python -m ruff check .`: PASSED
- `python -m pytest -q`: PASSED, 627 passed / 4 skipped / 62 warnings
- `node --check web/js/app.js`: PASSED

Global Python was not used as the authority because `ruff`/`psycopg` were absent and unrelated MoviePy/Pillow packages conflicted.

## 5. Confirmed defect

**CONFIRMED DEFECT — critical.** `build_production_drift_report` could return `CRITICAL`, but the only runtime consequence was `Worker.model_heartbeat_status()` returning `DEGRADED`. The hourly loop invoked `inference_job` before `drift_monitor_job`; `publish_hourly_signals`, `create_execution_plan` and `accept_recommendation` did not consult drift state.

Minimal behavior: with a persisted current-version `CRITICAL` report, the baseline lacked any guard contract, published the next hourly decision set, and allowed an existing `ACTIONABLE` plan through the normal acceptance path. Expected behavior from the embedded specification is fail-closed/no-trade or fallback under material degradation.

Impact: continued exposure to a model already diagnosed as critically shifted. This is a safety defect; it does not prove that previous losses were caused by drift and does not establish profitability after the fix. Existing tests verified drift metrics/heartbeat but not publication or acceptance consequences.

## 6. Plan and actual diff

Production:

- `app/services/drift_monitor.py`: exact-version persisted quarantine guard and report action metadata.
- `app/workers/runner.py`: explicit hourly safety order with drift before inference.
- `app/services/signals.py`: early publication short-circuit and per-symbol attrition.
- `app/services/execution.py`: central `NO_TRADE` override and persisted guard evidence.
- `app/api/v1/recommendations.py`: acceptance-time recheck and conflict precedence.
- `app/__init__.py`, `pyproject.toml`: version 1.27.0.

Tests:

- new `tests/unit/test_critical_drift_interlock_2026_07_06.py`;
- extended `tests/unit/test_execution_acceptance_safety.py` for plan and acceptance interlocks.

Docs/release: README, CHANGELOG, patch, QA, compliance, traceability, this report and regenerated `SHA256SUMS`. No migration or environment-variable change.

## 7. Red → green evidence

Original guard red:

```text
python -m pytest -q tests/unit/test_critical_drift_interlock_2026_07_06.py
```

Before implementation: collection error because the guard schema/function did not exist. After implementation: 4 passed.

Acceptance red:

```text
python -m pytest -q tests/unit/test_execution_acceptance_safety.py::test_acceptance_rejects_actionable_plan_after_critical_drift
```

First run: failed, actual HTTP 200 vs expected 409. The implementation had set a drift conflict but then overwritten it with plan-contract validation. After making validation conditional on no prior conflict: 1 passed.

Combined targeted green:

```text
python -m pytest -q tests/unit/test_critical_drift_interlock_2026_07_06.py tests/unit/test_execution_acceptance_safety.py
```

Result: 53 passed.

## 8. Compatibility

- Migration: none; Alembic head remains `0014_ui_exposure_ledger`.
- HTTP request/response schemas: unchanged; acceptance uses the existing 409 `PLAN_RECALCULATION_REQUIRED` contract.
- `.env`: unchanged.
- Model feature/label/runtime artifact schemas: unchanged.
- Risk, quality, economic and promotion thresholds: unchanged.
- Active current version is not deleted or auto-rolled back; its recommendations/plans are quarantined after persisted critical evidence.
- Activation of a different governed version releases the old-version latch by exact version matching; reactivating the same version does not. Stale runtime/signal versions fail closed. Disabling new monitor jobs does not clear persisted critical evidence.

## 9. Post-check

- `python -m pip check`: PASSED
- `python -m compileall -q app scripts tests manage.py`: PASSED
- `python -m ruff check .`: PASSED
- `python -m pytest -q`: PASSED, 636 passed / 4 skipped / 62 warnings
- `node --check web/js/app.js`: PASSED
- `alembic heads`: PASSED, single head `0014_ui_exposure_ledger`
- `sha256sum -c SHA256SUMS`: PASSED, 227 release files
- `unzip -t` and clean re-extraction: PASSED, one root directory and no forbidden artifacts

## 10. Not verified

- `manage.py doctor`: environment FAILED because `.env`, production secrets, PostgreSQL client tools and server are absent.
- `python manage.py test --require-integration`: FAILED preflight because `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` is unset; PostgreSQL integration tests were not executed.
- No live Bybit, forward profitability or recommendation-frequency evidence was available.
- Real multi-process activation/drift races were not exercised against PostgreSQL.

## 11. Residual risks

- Quarantine is model-version-wide, not symbol-specific; one critical aggregate report blocks the whole artifact.
- `BLOCKED` evidence does not quarantine by design; operator heartbeat remains the diagnostic until enough prospective observations exist.
- Drift thresholds remain univariate/fixed and may have false positives or false negatives.
- Automatic rollback is deliberately absent; the operator must activate another fully governed version.
- Rare recommendations and daily candidates failing gates remain unresolved. Defaults require substantial temporal evidence (README documents at least 1206 unique hourly timestamps before training gates can even be evaluated); weakening gates without measured attrition/mature outcomes would be unsafe.

## 12. Rollback

1. Stop API/inference/trainer processes.
2. Restore the 1.26.7 source archive; no database downgrade is required.
3. Restart services with the prior code.
4. Be aware that rollback restores the critical defect: drift remains heartbeat-only and a critically shifted artifact can continue publishing/accepting plans.

## 13. Recommended next work package

Use the prospective `candidate-live-attrition-report-v2` and mature outcomes to quantify where recommendations disappear: data completeness, model class/quality, policy economics, execution liquidity or portfolio risk. Select one measured dominant cause. Do not lower gates based only on sparse output or anecdotal losses.
