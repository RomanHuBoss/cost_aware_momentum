# QA Report

Release: **1.36.0**

Date: **2026-07-07**
Scope: **durable PostgreSQL-backed model artifacts and release-safe restoration**

## Environment

- Python: 3.13.5.
- Project requirement: Python >=3.12.
- Input archive: `cost_aware_momentum-main.zip`.
- Input SHA-256: `2b1a9b32ab68eb359a890580c5c6e325344d54479eaf641035d7a92f10fef830`.
- Source version: 1.35.5.
- Input Alembic head: `0016_universe_replay_asof`.
- Input inventory: 98 production/script Python files plus `manage.py`, 4 web files, 100 test Python files, 12 files in `docs/`, and 16 migration revisions.
- Separate PostgreSQL integration database: not configured.

The reproducible baseline and post-checks were run in the same isolated virtual environment installed from `pyproject.toml`.

## Baseline before production changes

| Check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 730 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED: one head, `0016_universe_replay_asof` |

`python manage.py doctor` and `python manage.py test --require-integration` were not run because the archive had no configured operator environment or isolated PostgreSQL test URL. The operator database was not accessed.

## Confirmed defect

The default `MODEL_DIR=models` is inside the deployed project directory. Candidate registration stored an absolute local path and SHA-256 in `model.model_registry`, but not the artifact bytes. The release boundary intentionally excludes real model files. Therefore this valid sequence was destructive:

`train candidate → register absolute path → deploy a clean ZIP / remove old release → registry survives in PostgreSQL → file disappears → runtime baseline fallback → recovery depends on a new candidate passing all gates`.

The supplied status screen showed that exact terminal state: an active trained registry version, `Artifact: файл отсутствует`, runtime source `registry_artifact_missing_fallback`, and effective model `baseline-momentum-v1`.

Severity: **HIGH**. Fail-closed baseline fallback prevented silent loading of an unverified model, but the validated incumbent was lost across deployment and the system could remain non-actionable until enough data and a successful governed retraining existed.

## Red evidence

The final eight regression tests were copied into the untouched 1.35.5 tree and run with:

```text
python -m pytest -q tests/unit/test_durable_model_artifact_store_2026_07_07.py
```

Result: **8 failed**. Failures independently established that:

- ORM and migration storage did not exist;
- verified restore and immutable archive functions did not exist;
- candidate registration did not pass exact bytes into its registry transaction;
- worker runtime selection had no artifact-durability step.

## Implemented correction

- Added immutable `model.model_artifact_blobs` storage with registry UUID/version/SHA-256/size binding.
- Added 256 MiB fail-closed limit, payload-size constraint, foreign key and PostgreSQL UPDATE/DELETE rejection trigger.
- Candidate registration stores exact bytes in the same transaction as `ModelRegistry`, audit and outbox.
- Added idempotent archive and SHA-verified atomic restore service.
- Worker restores before `select_model_runtime`; trainer restores before active-model recovery logic and pending-candidate promotion checks.
- Manual/automatic registered activation restores before runtime validation.
- Existing valid pre-1.36.0 files are archived lazily.
- Added worker heartbeat, status API and trainer-dialog diagnostics for archive and restore state.
- No model quality, policy, activation, cost, spread, EV/RR or risk gate was changed.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| focused new regression suite | PASSED: 8 passed |
| `python -m pytest -q` | PASSED: 738 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED: one head, `0017_model_artifact_blobs` |
| release integrity / checksum manifest | PASSED — 257 files checked, 257 manifest entries |

The additional skipped test is the new PostgreSQL append-only artifact integration contract; all integration tests remain skipped without `TEST_DATABASE_URL`.

## Migration and operator action

- Required: `python manage.py migrate` before starting release 1.36.0 processes.
- New `.env` variables: none.
- Preserve the old release directory until the first successful durability check if it may contain the only surviving active artifact.
- Restart API, worker and trainer after migration.
- Verify `/api/v1/status` or the trainer dialog shows an available PostgreSQL archive.

## Not run / residual limitations

- Actual migration, trigger behavior and binary round-trip were not executed on PostgreSQL in this environment.
- Real service restart and restoration from the operator database were not performed.
- Migration cannot recover bytes that were already deleted before 1.36.0 and exist nowhere else.
- PostgreSQL backups now contain model bytes and may grow; each artifact is limited to 256 MiB, but operational backup sizing was not profiled.
- The separate `not_enough_history_for_bootstrap` / 1206-hour requirement, point-in-time universe replay coverage and the candidate's walk-forward/holdout/trade-rate failures were not weakened or claimed fixed by this iteration.
- Technical recovery does not establish strategy profitability or explain historical losses.
