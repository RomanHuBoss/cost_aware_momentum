# Iteration report: durable model artifact storage

Date: **2026-07-07**
Release: **1.36.0**

## 1. Input and baseline identity

- Input archive: `cost_aware_momentum-main.zip`.
- Input SHA-256: `2b1a9b32ab68eb359a890580c5c6e325344d54479eaf641035d7a92f10fef830`.
- Actual source version: 1.35.5.
- Python requirement: >=3.12; tested with 3.13.5.
- Input Alembic head: `0016_universe_replay_asof`.
- Input inventory: 98 production/script Python files plus `manage.py`, 4 web files, 100 test Python files, 12 files in `docs/`, and 16 migration revisions.
- Input release contained no `.env`, virtual environment, database dump or real model artifact. Generated test caches and egg-info were created only in the working tree and are excluded from the final archive.

## 2. Goal and acceptance criteria

After this iteration, a registered model must survive replacement of its release directory because exact verified artifact bytes are durably bound to its PostgreSQL registry row and can recreate the runtime file before selection or activation.

Acceptance criteria:

1. new candidate registration archives exact bytes atomically with registry/audit/outbox state;
2. stored version, SHA-256, size and payload are immutable and internally consistent;
3. worker repairs a missing active file before runtime selection;
4. trainer repairs active and pending-candidate files before recovery/promotion decisions;
5. registered activation repairs before artifact validation;
6. corrupt or mismatched DB bytes fail closed and are never written as a runtime artifact;
7. existing corrupt local evidence is not overwritten;
8. UI/status exposes archive and repair state;
9. existing quality, holdout, walk-forward, promotion, EV/RR and risk gates remain unchanged;
10. full suite and release checks remain green.

## 3. Sources and affected data flow

Read: `README.md`, `CHANGELOG.md`, patches 1.35.2–1.35.5, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `pyproject.toml`, `.env.example`, model lifecycle/runtime selection/activation, worker, trainer, status API/UI, migrations, release integrity policy and related tests. Several architecture/configuration/manual documents named by the iterative prompt do not exist in this archive; no files were invented under those names.

Observed flow before correction:

`trainer writes models/*.joblib → ModelRegistry stores absolute path + SHA → release ZIP excludes *.joblib → old release removed → path missing → baseline fallback → governed recovery retraining`.

Corrected flow:

`candidate bytes read once → SHA/size validation → ModelRegistry + immutable BYTEA + audit/outbox commit together → local runtime copy checked → missing copy restored atomically → normal runtime/activation validator loads exact bytes`.

## 4. Baseline

- `python --version`: Python 3.13.5, PASSED;
- `python -m pip check`: PASSED;
- `python -m compileall -q app scripts tests manage.py`: PASSED;
- `python -m ruff check .`: PASSED;
- `python -m pytest -q`: 730 passed, 7 skipped, 62 warnings, PASSED;
- `node --check web/js/app.js`: PASSED;
- `python -m alembic heads`: one head `0016_universe_replay_asof`, PASSED.

`manage.py doctor` and PostgreSQL integration were not run because no operator configuration or isolated test database was available.

## 5. Confirmed defect

### DEFECT-1 — release-local artifact was the only byte source (high)

Files/functions:

- `app/config.py::Settings.model_dir` defaulted to `models`;
- `app/ml/lifecycle.py::register_model_candidate` and `register_and_activate_model_candidate` stored only path/hash metadata;
- `scripts/release_integrity.py` correctly forbade `*.joblib` in release archives;
- `app/ml/runtime_selection.py` detected the missing path and fell back to baseline.

Minimal reproduction:

1. train and register a candidate in release directory A;
2. retain PostgreSQL but deploy clean release directory B;
3. remove A, as is normal during replacement/cleanup;
4. registry still names A/models/version.joblib, but bytes no longer exist;
5. worker selects baseline and trainer enters recovery scheduling.

Expected: immutable model state survives code deployment.
Actual: durable DB metadata survived, but the only artifact bytes did not.

Impact: loss of a validated incumbent, non-actionable baseline runtime, repeated recovery work and possible long waiting on bootstrap/quality gates. Fail-closed behavior limited financial harm but did not prevent operational loss.

Why tests missed it: tests validated hash/path loss fallback and recovery scheduling inside one filesystem tree, not deletion of the release tree after registry commit.

### Observed but not changed in this scope

- `not_enough_history_for_bootstrap` at the default 1206 unique hourly timestamps;
- prior candidate failures for walk-forward policy stability, holdout span and trade rate;
- spread-based live attrition for instruments above the 18 bps execution threshold.

These are separate data/econometric work packages. No threshold was lowered to conceal them.

## 6. Plan and actual diff

Production:

- `app/db/models.py`: `ModelArtifactBlob` ORM contract.
- `app/ml/artifact_store.py`: archive, validation and atomic restore service.
- `app/ml/lifecycle.py`: transactional archive at candidate registration.
- `app/workers/runner.py`: restore/archive before runtime selection; heartbeat evidence.
- `app/workers/trainer.py`: restore/archive before active recovery and pending promotion.
- `app/services/model_activation.py`: restore/archive before activation validation.
- `app/api/v1/status.py`, `web/js/app.js`: archive/durability diagnostics.
- `app/__init__.py`, `pyproject.toml`: version 1.36.0.

Migration:

- `migrations/versions/0017_model_artifact_blobs.py`.

Tests:

- `tests/unit/test_durable_model_artifact_store_2026_07_07.py`;
- migration-head/runtime/activation test adjustments;
- PostgreSQL migration and append-only integration contract.

Documentation:

- `README.md`, `CHANGELOG.md`, `PATCH_1.36.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this report.

## 7. Red → green evidence

Command on untouched 1.35.5 with the final new test file copied in:

```text
python -m pytest -q tests/unit/test_durable_model_artifact_store_2026_07_07.py
```

Red: **8 failed**. The missing ORM/migration/module, absent exact-byte registration binding and absent pre-selection durability step failed for the intended reasons.

The same command on 1.36.0: **8 passed**.

The tests use independent SHA-256 values, exact byte comparisons, a corrupt payload, a pre-existing corrupt file and call-order recording. They do not use the implementation output as their oracle.

## 8. Migration, API/config and compatibility

- New head: `0017_model_artifact_blobs`.
- Upgrade creates an append-only BYTEA table under schema `model`.
- Downgrade drops trigger/function/table; registry rows remain.
- No `.env` changes.
- Status API adds `active_model.artifact_archive` and `active_model.artifact_durability`; existing fields remain.
- No model-bundle, feature, label, probability, policy, risk or recommendation schema change.
- Maximum archived artifact size is 256 MiB; larger candidates fail registration atomically.

## 9. Post-check

- `python -m pip check`: PASSED;
- compileall: PASSED;
- Ruff: PASSED;
- focused new suite: 8 passed;
- full pytest: 738 passed, 8 skipped, 62 warnings;
- Node syntax: PASSED;
- Alembic: one head `0017_model_artifact_blobs`;
- migration revision contract: PASSED.

Final release integrity, ZIP test and SHA-256 are performed after report generation and recorded in the user response.

## 10. Not verified

- Real PostgreSQL migration and binary payload round-trip.
- Trigger behavior on the operator PostgreSQL version.
- Actual worker/trainer/API restart and restoration from the operator database.
- Backup size and restore duration with a long artifact history.
- Windows filesystem restore path; unit tests ran on Linux.

## 11. Residual risks and limitations

- Migration cannot reconstruct a pre-1.36.0 artifact whose only file has already been deleted.
- A database commit failure after an atomically restored local file may leave an unreferenced verified copy; the next check is idempotent, and release packaging excludes it.
- PostgreSQL backup volume increases by exact artifact size. A hard 256 MiB per-artifact cap limits one row but not total registry growth.
- This fix restores model-state durability; it does not prove model edge, correct previous losses, or solve insufficient point-in-time training history.

## 12. Rollback and next work package

Rollback:

1. stop API/worker/trainer;
2. restore 1.35.5 code;
3. optionally run `alembic downgrade 0016_universe_replay_asof` only after verifying no 1.36.0-only recovery dependency is needed;
4. restart services.

Keeping migration 0017 while running old code is not supported because readiness expects the code's head. Downgrade deletes archived bytes, so preserve PostgreSQL backup and surviving artifact files first.

Recommended next work package: instrument and prove why the 365-day backfill still yields fewer than the required 1206 point-in-time eligible hourly timestamps, separating candle ingestion, confirmed/availability filtering and prospective universe-replay exclusion. Do not lower holdout or walk-forward requirements until that evidence is available.
