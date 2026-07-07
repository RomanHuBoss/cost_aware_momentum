# QA Report

Release: **1.49.1**
Date: **2026-07-07**
Scope: **fresh PostgreSQL migration recovery after duplicate-column failure**

## Environment and input

- Python: 3.13.5; project requirement: Python >=3.12.
- Input archive: `cost_aware_momentum-main.zip`.
- Input SHA-256: `06b3a487624e8cae6c2b5ba3dd876c34d43cd73e4b60aac1bc80405555068be0`.
- Source version: 1.49.0.
- Source inventory: 98 production/script Python files, 112 test files, 26 documentation files and 17 migrations.
- Alembic head before and after: `0017_model_artifact_blobs`.
- Separate PostgreSQL integration database: not configured in the build environment.

## Baseline before production changes

| Check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 828 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | UNAVAILABLE for release validation: no project `.env`, PostgreSQL client tools or running PostgreSQL server |
| `python manage.py test --require-integration` | NOT RUN: test runner stopped because neither `POSTGRES_ADMIN_URL` nor `TEST_DATABASE_URL` was configured |

The eight skipped tests are PostgreSQL integration tests. No production database was accessed.

## Confirmed defect and red evidence

The operator's clean migration log reproduced a deterministic failure at `0006_manual_trade_remaining_risk`:

```text
psycopg.errors.DuplicateColumn: column "initial_stress_loss" of relation "manual_trades" already exists
```

Static data-flow inspection proved the root cause:

1. `0001_initial.upgrade()` imports the current ORM and calls `Base.metadata.create_all(bind=bind)`.
2. Current `ManualTrade` metadata already contains `initial_stress_loss` and `remaining_stress_loss`.
3. Released revision `0006` attempted to add both columns unconditionally.
4. Current metadata also contains `PositionSnapshot.account_id`/`ix_position_account_time` and `ModelArtifactBlob`, so fixing only `0006` would expose later duplicate-object failures in `0007` and `0017`.

A new regression was first run against the unmodified migration sources:

```text
FAILED test_post_initial_revisions_tolerate_objects_created_by_current_metadata
assert "ADD COLUMN IF NOT EXISTS INITIAL_STRESS_LOSS" in manual_risk
1 failed
```

## Post-change verification

| Check | Result |
|---|---|
| New migration compatibility regression | PASSED: 1 passed |
| Focused migration/account/artifact/econometric compatibility set | PASSED: 74 passed |
| Alembic PostgreSQL offline SQL, base → head | PASSED: all 17 revisions generated; recovery guards present |
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 829 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic graph | PASSED: one head, `0017_model_artifact_blobs` |
| `python manage.py doctor` | FAILED as expected in this environment: no `.env`, PostgreSQL tools/server; code and package checks passed |
| `python manage.py test --require-integration` | NOT RUN: isolated PostgreSQL URL unavailable |

## Release boundary

- Patch release 1.49.1.
- No new Alembic revision; head remains `0017_model_artifact_blobs`.
- No `.env` changes.
- No API, UI, model artifact schema, trading logic, risk mathematics or econometric threshold changes.
- Historical revisions `0006`, `0007` and `0017` were made compatible with the existing `0001` current-metadata design.
- `0006` preserves existing non-null values and backfills only null values before exact constraint recreation.
- Existing databases already at head do not rerun these revisions.
- Failed/clean installations should replace files and rerun `python manage.py migrate`; manual column deletion and `alembic stamp` are explicitly not required.

## Residual limitations

- The patched chain was not executed against a live isolated PostgreSQL server in the build environment. The operator's rerun is the final environment-specific confirmation.
- `0001_initial` still depends on current ORM metadata. The new regression covers all currently known overlapping revisions, but future migrations must remain fresh-install-idempotent or the initial schema must eventually be frozen in a separately planned compatibility change.
- Existing model, policy, drift and profitability evidence was not re-evaluated; this patch only repairs schema installation/recovery correctness.
