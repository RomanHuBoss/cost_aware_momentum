# Iteration report — deferred model promotion

## 1. Input and baseline identity

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `a15abeda32c786ebbc6ca952168386b0938133f0900fd0ea54eb5ec3b2418952`
- Input version: `1.26.1`
- Input root: one directory, `cost_aware_momentum-main/`
- Input files: 204 total; 96 production (`app/`, `scripts/`, `web/`), 79 tests, 2 documentation files.
- Alembic revisions: `0001_initial` through `0014_ui_exposure_ledger`; single declared head `0014_ui_exposure_ledger` by source inspection.
- Unexpected release artifacts: no `.env`, virtual environment, Python caches, build/dist directories, dumps or real model artifacts were present.
- Repository documentation gap at input: `CHANGELOG.md`, `PATCH_*.md`, `docs/QA_REPORT.md` and `docs/TRACEABILITY.md` were absent.

## 2. Iteration goal and acceptance criteria

Goal: after this iteration, a quality-passed immutable candidate registered inactive by the background trainer can be promoted on a later scheduling iteration when exact preregistered experiment evidence becomes `READY`, without weakening any gate or retraining the model.

Acceptance criteria:

1. Trainer discovers only inactive background candidates with `activation_requested=true` and a valid persisted quality gate.
2. Missing/non-READY/mismatched experiment evidence remains fail-closed.
3. Evidence is bound to exact candidate version, SHA-256 and horizon.
4. A fresh gate is recomputed under lock before database mutation.
5. Artifact runtime validation, active-version compare-and-swap, audit and outbox remain mandatory.
6. Successful promotion prevents an immediate second training run in the same scheduler cycle.
7. CLI and trainer use one activation implementation.
8. Full unit/static suite has no regression.

## 3. Sources and data flow

Read or inspected:

- `README.md`, `.env.example`, `pyproject.toml`, `docs/SPEC_COMPLIANCE.md`
- source specification `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`
- `app/workers/trainer.py`
- `app/ml/lifecycle.py`, `app/ml/runtime.py`
- `app/services/model_promotion.py`, `app/services/experiment_ledger.py`
- `scripts/model_registry.py`
- activation, experiment-binding, atomic-promotion and trainer tests

Changed data flow:

`registered inactive ModelRegistry candidate` → `persisted quality-gate validation` → `configured/stored experiment family` → `exact-artifact experiment report evaluation` → `transactional locked recheck` → `artifact runtime validation` → `active registry update + audit + outbox` → `trainer heartbeat/state`.

## 4. Baseline

A first attempt in the host Python environment was unsuitable: unrelated package conflicts caused `pip check` failure, `ruff` was absent, and pytest collection produced 32 import errors because project dependencies including `psycopg` were not installed.

A clean editable project venv was created and used for both baseline and post-check:

- `python -m pip check`: PASSED
- `python -m compileall -q app scripts tests manage.py`: PASSED
- `python -m ruff check .`: PASSED
- `python -m pytest -q`: PASSED — 606 passed, 4 skipped, 61 warnings
- `node --check web/js/app.js`: PASSED

## 5. Confirmed defect

### HIGH — background auto-activation could not complete a staged lifecycle

Classification: **CONFIRMED DEFECT**.

Evidence:

- `app/workers/trainer.py::run_training_once` creates a new unique artifact, computes a gate immediately and registers it inactive when exact family evidence is not yet ready.
- Exact preregistration/backtests necessarily depend on the newly known candidate version/SHA-256/horizon.
- `BackgroundTrainer.run_scheduling_iteration` previously called only `due_reason()` and optional `run_training_once()`; it had no path that revisited a registered candidate.
- Manual CLI activation existed, but `AUTO_TRAIN_AUTO_ACTIVATE=true` did not provide eventual background activation.

Expected behavior: after external preregistered research evidence becomes `READY`, the trainer rechecks and atomically promotes the same immutable artifact.

Actual behavior: the candidate remained inactive indefinitely unless the operator invoked the manual registry CLI.

Impact: operational model lifecycle stall, repeated inactive candidates and continued use of the incumbent/baseline despite completed evidence. This explains a class of “trained models never cross into active state”; it does not by itself prove the cause of losing trades or economic underperformance.

Why tests missed it: existing tests covered same-call atomic promotion and manual activation gates, but not a two-stage transition across separate scheduler iterations.

## 6. Plan and actual diff

Production:

- Added `app/services/model_activation.py` as the shared registered-artifact activation boundary.
- Added pending-candidate discovery and deferred reconciliation to `app/workers/trainer.py`.
- Updated `scripts/model_registry.py` to use the shared service.
- Documented staged family configuration in `app/config.py` and `.env.example`.

Tests:

- Added `tests/unit/test_deferred_model_promotion.py`.
- Redirected existing activation tests from script-local logic to the shared production service, preserving assertions.

Documentation/version:

- Bumped `1.26.1` → `1.26.2`.
- Updated `README.md` and `docs/SPEC_COMPLIANCE.md`.
- Added `CHANGELOG.md`, `PATCH_1.26.2.md`, `docs/QA_REPORT.md`, `docs/TRACEABILITY.md` and this report.

## 7. Red → green

Red command:

```text
python -m pytest -q tests/unit/test_deferred_model_promotion.py
```

Before production changes: 2 failed with `AttributeError` because the pending-candidate and reconciliation methods did not exist.

Green command: same file after implementation — 3 passed. The added fail-closed case confirms that a blocked report never invokes activation.

## 8. Migration, API and configuration compatibility

- Migration: none.
- API: unchanged.
- Artifact contract: unchanged.
- Risk/quality/PBO/DSR thresholds: unchanged.
- New documented operator setting: `AUTO_TRAIN_EXPERIMENT_FAMILY=`. It may remain empty; candidate stays inactive.
- Trainer restart is required after changing `.env` because settings are process-local.
- `ACTIVE_MODEL_PATH` continues to disable registry auto-promotion.

## 9. Post-check

Pre-documentation full check:

- `pip check`: PASSED
- `compileall`: PASSED
- `ruff`: PASSED
- `pytest`: PASSED — 609 passed, 4 skipped, 61 warnings
- `node --check`: PASSED
- static Alembic head: PASSED — `0014_ui_exposure_ledger`
- version consistency: PASSED — `pyproject.toml` and `app.__version__` are `1.26.2`
- release integrity: PASSED — 211 eligible files and 211 manifest entries before packaging

Additional environment checks:

- `python manage.py doctor`: FAILED as an environment readiness check — `.env` was intentionally absent from the release workspace, default secrets were therefore detected, PostgreSQL client tools were unavailable and no local PostgreSQL server was running.
- `python manage.py test --require-integration`: NOT RUN — neither `TEST_DATABASE_URL` nor `POSTGRES_ADMIN_URL` was configured, so no safe isolated PostgreSQL database could be created.

Final archive integrity and SHA are recorded in the final response.

## 10. Not verified

- PostgreSQL integration suite and real concurrent-session locking: no dedicated test database was configured.
- Bybit network behavior: unchanged and not exercised.
- Economic profitability, recommendation frequency and forward/live edge: not established by this patch.
- Existing active/inactive rows in the user's database were not available for migration-free smoke testing.

## 11. Residual risks and limitations

- Trainer does not create preregistration or execute backtests automatically.
- Only the newest quality-passed background candidate is considered automatically; older candidates require explicit CLI review.
- A `READY` experiment report can still fail atomic activation if the artifact changed, the active version raced, the family changed, or runtime metadata is incompatible.
- The user's reported losses require separate prospective outcome/selection/cost attribution; loosening gates would be unsafe.

## 12. Rollback

1. Stop trainer/API/worker.
2. Restore release 1.26.1 source files.
3. Restart services; no database downgrade is required.
4. Any model activated under 1.26.2 remains a normal registry row. If rollback of the active model is required, use the reviewed `model-registry activate` workflow with exact evidence or the explicit reasoned emergency override.

## 13. Recommended next work package

Run a prospective “rare recommendation and realized loss attribution” package using candidate/live attrition, mature outcomes, drift report and accepted-trade execution evidence. The goal should be to identify whether losses originate in model calibration, policy selection, execution-cost mismatch, operator selection or regime drift before changing thresholds or trading logic.
