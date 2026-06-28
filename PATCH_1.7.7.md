# Patch 1.7.7 — controlled orphan model recovery and diagnostics

## Problem

The UI reported only the stale active registry version when its `.joblib` was missing. A newer file in `models/` could be:

- an inactive registered candidate rejected by quality gates;
- a gate-passed candidate whose activation did not finish;
- an orphan artifact created before registry insertion completed.

All three cases were displayed as generic baseline degradation with “ожидание новых данных”. Merely copying a `.joblib` into the directory could not and should not silently replace the active registry model.

## Change

- `/api/v1/status` now exposes the latest inactive candidate, artifact existence, stored gate result/reasons and up to ten unregistered `.joblib` filenames.
- The frontend shows whether the candidate failed a quality gate, passed but was not activated, or is absent from model registry.
- Trainer wait state now distinguishes quality-gate cooldown and technical recovery backoff from ordinary waiting for new data.
- Added `python manage.py model-registry recover-artifact --artifact models/<artifact>.joblib`.
- Recovery is allowed only outside production, with baseline explicitly enabled and no usable trained active artifact.
- The command requires the file to be inside `MODEL_DIR`, validates task, feature schema, classes, filename/version, horizon and training profile, then re-runs absolute ML/policy gates.
- A passing orphan is registered with SHA256/audit/outbox metadata and activated through the existing guarded activation path.
- A failed candidate is registered or kept inactive and is never promoted automatically.

## Compatibility

- Patch release; no Alembic migration is required. Head remains `0005_plan_outcome_invalid_input`.
- No new `.env` variables are required.
- Existing active trained models and normal trainer promotion are unchanged.
- This command is a recovery path, not a general bypass of incumbent-relative promotion or production integrity checks.

## Verification

- RED: targeted tests failed during collection because `app.ml.artifact_recovery`, candidate diagnostics and recovery flow were absent.
- GREEN targeted: `17 passed` for artifact reconstruction, mismatch/horizon rejection, orphan diagnostics, passing recovery activation and failed-gate preservation.
- Full post-check results are recorded in `docs/QA_REPORT.md` and `docs/ITERATION_REPORT_2026-06-28-model-artifact-reconciliation.md`.
