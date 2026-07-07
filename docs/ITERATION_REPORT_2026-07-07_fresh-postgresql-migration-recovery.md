# Iteration report — fresh PostgreSQL migration recovery

## 1. Input archive and source state

- Input: `cost_aware_momentum-main.zip`
- SHA-256: `06b3a487624e8cae6c2b5ba3dd876c34d43cd73e4b60aac1bc80405555068be0`
- Source version: 1.49.0
- Target version: 1.49.1
- Python requirement: >=3.12
- Alembic head: `0017_model_artifact_blobs`
- Input inventory: 98 production/script Python files, 112 test files, 26 documentation files, 17 migrations, 298 total files.
- Input release tree contained no `.env`, virtual environment, bytecode/cache directories, model artifacts or database dumps.

## 2. Iteration goal and acceptance criteria

Goal:

> After this iteration, a clean PostgreSQL database or the reported database stopped before `0006` can continue `python manage.py migrate` to the existing head without duplicate-object DDL, manual column deletion or `alembic stamp`, while preserving existing data and constraints.

Acceptance criteria:

1. `0006` tolerates pre-existing risk columns and preserves non-null values.
2. `0006` backfills missing values and reasserts exact `NOT NULL`/check constraints.
3. `0007` tolerates pre-existing `account_id` and index.
4. `0017` tolerates a pre-existing artifact table/function and restores the intended PostgreSQL `created_at` server default.
5. Alembic retains one unchanged head.
6. A regression fails on 1.49.0 and passes after the fix without PostgreSQL-dependent skipping.
7. Full static/unit checks do not regress.
8. Recovery instructions do not require destructive schema edits.

## 3. Sources read and affected data flow

Read:

- current user traceback;
- attached iterative-development master prompt;
- `README.md`, `CHANGELOG.md`, `PATCH_1.48.0.md`, `PATCH_1.49.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- `pyproject.toml`, `.env.example`, `alembic.ini`, `migrations/env.py`;
- all 17 migration revisions;
- `app/db/base.py`, relevant ORM models and migration/integration tests.

The archive does not contain `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/CONFIGURATION.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md` or `docs/MODEL_CARD.md`; no such files were assumed or fabricated. No DOCX specification was attached to this iteration.

Affected flow:

`python manage.py migrate` → Alembic PostgreSQL transaction → `0001` current ORM `create_all()` → later overlap revisions → `alembic_version` → API/worker/trainer readiness.

## 4. Baseline

Environment: Python 3.13.5 in an isolated virtual environment.

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 828 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | UNAVAILABLE for operational validation: no `.env`, PostgreSQL tools/server |
| `python manage.py test --require-integration` | NOT RUN: no `POSTGRES_ADMIN_URL`/`TEST_DATABASE_URL` |

## 5. Confirmed defects and evidence

### MIG-001 — duplicate risk columns at revision 0006

- Classification: `CONFIRMED DEFECT`
- Severity: high
- Files: `migrations/versions/0001_initial.py`, `0006_manual_trade_remaining_risk.py`, `app/db/models.py`
- Evidence: operator PostgreSQL traceback plus deterministic source path.
- Expected: clean base → head migration succeeds.
- Actual: `0001` creates current risk columns; `0006` adds them again and raises `DuplicateColumn`.
- Impact: first installation and recovery are blocked before the application can start.
- Why tests missed it: the existing base → head integration fixture was skipped when no isolated PostgreSQL URL was configured; unit tests did not enforce overlap idempotency.

### MIG-002 — latent duplicate account column/index at revision 0007

- Classification: `CONFIRMED DEFECT`
- Severity: high
- Files: `0001_initial.py`, `0007_position_account_scope.py`, `PositionSnapshot`
- Evidence: current metadata already defines both objects; `0007` used unconditional `op.add_column`/`op.create_index`.
- Impact: fixing only `0006` would move the same clean installation to another deterministic failure.

### MIG-003 — latent duplicate artifact table/function at revision 0017

- Classification: `CONFIRMED DEFECT`
- Severity: high
- Files: `0001_initial.py`, `0017_model_artifact_blobs.py`, `ModelArtifactBlob`
- Evidence: current metadata already creates the table; `0017` used unconditional table/function DDL.
- Additional mismatch: ORM's Python-side `created_at` default does not create the PostgreSQL `DEFAULT now()` declared by `0017` when the table originated in `0001`.
- Impact: fresh install would fail near head or silently miss the intended server default if guarded only by `CREATE TABLE IF NOT EXISTS`.

## 6. Plan and actual diff

Production/migration files:

- `migrations/versions/0006_manual_trade_remaining_risk.py`
- `migrations/versions/0007_position_account_scope.py`
- `migrations/versions/0017_model_artifact_blobs.py`
- `app/__init__.py`
- `pyproject.toml`

Tests:

- added `tests/unit/test_migration_fresh_install_compatibility_2026_07_07.py`;
- strengthened `tests/unit/test_durable_model_artifact_store_2026_07_07.py`;
- strengthened `tests/integration_postgres/test_migrations_and_audit.py`.

Documentation/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.49.1.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this iteration report;
- regenerated `SHA256SUMS` after final cleanup.

No API/config/env/model/risk changes and no new migration revision.

## 7. Red → green evidence

Command:

```text
python -m pytest -q tests/unit/test_migration_fresh_install_compatibility_2026_07_07.py
```

Red on untouched migration sources:

```text
1 failed
assert "ADD COLUMN IF NOT EXISTS INITIAL_STRESS_LOSS" in manual_risk
```

Green after patch:

```text
1 passed
```

Focused compatibility result:

```text
74 passed
```

The regression checks the independent compatibility invariant established by `0001`: every later revision that overlaps current metadata must tolerate pre-existing objects.

## 8. Migration/API/config compatibility

- Head unchanged: `0017_model_artifact_blobs`.
- No new migration is required.
- Existing databases at head are unaffected because Alembic does not rerun historical revisions.
- The reported failed database should retain the last committed revision because PostgreSQL transactional DDL is enabled.
- Recovery: install 1.49.1 and rerun `python manage.py migrate`.
- Do not drop columns and do not stamp the database.
- `.env`: unchanged.
- API/UI/model artifact contracts: unchanged.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 829 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic offline PostgreSQL `upgrade head --sql` | PASSED; all recovery guards emitted |
| Alembic heads | PASSED: `['0017_model_artifact_blobs']` |
| Focused migration/account/artifact/econometric set | PASSED: 74 passed |

## 10. Not verified

- Live base → head migration on an isolated PostgreSQL server was not run because PostgreSQL binaries/server and a test URL were unavailable.
- `python manage.py doctor` could not pass without project secrets/configuration, PostgreSQL client binaries and a running server.
- `python manage.py test --require-integration` stopped before pytest because no isolated PostgreSQL URL was configured.
- No production database, Bybit account or network endpoint was accessed.

## 11. Residual risks and limitations

- The architecture still couples `0001` to current ORM metadata. Current overlapping revisions are guarded and unit-enforced, but a future unguarded revision could recreate the class of defect.
- Offline SQL generation validates Alembic/Python/DDL emission, not PostgreSQL execution semantics or locks on a populated database.
- This patch does not claim strategy profitability and does not alter mathematical, ML or policy gates.

## 12. Rollback

Code rollback is replacement with 1.49.0. This is not recommended for a clean/failed installation because it restores the deterministic duplicate-object failure.

For a database already at head, reverting application files does not change schema because 1.49.1 adds no revision. Do not manually downgrade/drop the risk/account/artifact objects solely to roll back this patch.

## 13. Recommended next work package

Freeze the historical `0001` schema or add mandatory ephemeral-PostgreSQL base → head and partial-recovery jobs to CI, so future migration compatibility is proven by execution rather than only by source/offline contracts. This work was not implemented in the present iteration.
