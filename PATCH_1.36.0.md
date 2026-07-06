# Patch 1.36.0 — durable model artifact storage

Date: 2026-07-07

## Problem

`MODEL_DIR=models` placed trained artifacts inside the currently deployed release tree. `ModelRegistry.artifact_path` stored that resolved filesystem path, while the release integrity policy correctly excluded real `*.joblib` files from ZIP archives. Replacing or deleting the previous release directory therefore left PostgreSQL pointing to a file that no longer existed.

The supplied trainer screen reproduced the resulting state: a trained registry version remained active, its artifact file was absent, runtime fell back to `baseline-momentum-v1`, and recovery required a new candidate to pass all history, walk-forward, holdout and policy gates. This was an operational state-loss defect, not a reason to weaken those gates.

## Correction

- Added `model.model_artifact_blobs`, keyed by `ModelRegistry.id`, with exact version, SHA-256, size and `BYTEA` payload.
- Added PostgreSQL constraints and an UPDATE/DELETE rejection trigger; payloads over 256 MiB are rejected.
- Candidate registration reads exact bytes once and stores them in the same transaction as registry, audit and outbox state.
- Worker and trainer lock the registry row, verify the local file, lazily archive existing pre-1.36.0 files, or atomically restore a missing file from PostgreSQL before runtime/recovery decisions.
- Registered activation performs the same repair before validating the artifact.
- Restore uses a temporary file, `fsync`, SHA-256 verification and atomic `os.replace`; an existing corrupt file is not overwritten.
- Worker heartbeat, `/api/v1/status` and the trainer dialog expose archive/durability state.

## Compatibility

- Required migration: `0017_model_artifact_blobs`.
- New `.env` variables: none.
- Feature, label, probability, model-bundle and policy schemas: unchanged.
- Quality, walk-forward, holdout, experiment-promotion, EV/RR, leverage and risk thresholds: unchanged.
- Advisory-only and read-only Bybit boundaries: unchanged.
- Existing valid artifacts are archived on first worker/trainer/activation check.
- A pre-1.36.0 artifact that is already missing cannot be reconstructed without another surviving copy; governed recovery training remains required.

## Validation

Baseline 1.35.5:

- `730 passed, 7 skipped, 62 warnings`;
- pip check, Ruff, compileall, JavaScript syntax and Alembic head `0016_universe_replay_asof` passed in an isolated environment.

Red evidence against unmodified 1.35.5:

- `tests/unit/test_durable_model_artifact_store_2026_07_07.py`: `8 failed` because the DB model/migration/store were absent, registration did not pass exact bytes, and worker runtime selection had no durability step.

Release 1.36.0:

- focused regression suite: `8 passed`;
- full suite: `738 passed, 8 skipped, 62 warnings`;
- pip check, Ruff, compileall, JavaScript syntax and Alembic single head `0017_model_artifact_blobs` passed.

PostgreSQL integration was not executed because no isolated `TEST_DATABASE_URL` or `POSTGRES_ADMIN_URL` was available. The integration suite now verifies the new head/table and append-only trigger when such a database is supplied.

## Operator action

1. Preserve any old release directory that may still contain the active `*.joblib` file.
2. Stop API, worker and trainer.
3. Replace the application files.
4. Run `python manage.py migrate`.
5. Start API, worker and trainer.
6. Open «Обучатель моделей» and confirm `PostgreSQL archive` is available and `Проверка artifact` reports archived/available/restored.

If the old active file has already been deleted and the archive row does not exist, migration alone cannot recreate it. Keep baseline fallback fail-closed and use the existing governed recovery-training path; do not lower holdout, walk-forward or trade-rate gates merely to force activation.
