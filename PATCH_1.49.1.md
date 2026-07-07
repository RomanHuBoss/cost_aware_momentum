# Patch 1.49.1 — fresh PostgreSQL migration recovery

## Problem

A clean `python manage.py migrate` could stop at revision `0006_manual_trade_remaining_risk` with:

```text
psycopg.errors.DuplicateColumn: column "initial_stress_loss" of relation "manual_trades" already exists
```

The root cause was not an operator-created duplicate. Revision `0001_initial` intentionally calls `Base.metadata.create_all()`, so a clean database receives the **current** ORM schema, including objects introduced by later revisions. Most later migrations already used `IF NOT EXISTS`, but three released revisions did not fully honor that compatibility contract:

- `0006` unconditionally added `manual_trades.initial_stress_loss` and `remaining_stress_loss`;
- `0007` unconditionally added `position_snapshots.account_id` and its index;
- `0017` unconditionally created `model.model_artifact_blobs` and its trigger function.

Fixing only `0006` would merely move a clean installation to the next duplicate-object failure.

## Solution

### Revision 0006

- Adds each risk column with `IF NOT EXISTS`.
- Preserves non-null existing values.
- Backfills only missing values from the linked execution plan.
- Drops and recreates the three exact risk constraints inside the migration transaction.
- Reasserts both columns as `NOT NULL`.
- Uses `IF EXISTS` during downgrade.

### Revision 0007

- Adds `account_id` with `IF NOT EXISTS`.
- Backfills only null legacy rows.
- Reasserts `NOT NULL`.
- Creates the account/time index with `IF NOT EXISTS`.
- Uses guarded downgrade operations.

### Revision 0017

- Creates the artifact table with `IF NOT EXISTS`.
- Reasserts `created_at DEFAULT now()` because SQLAlchemy's Python-side default is not a PostgreSQL server default when `0001` creates the current table.
- Uses `CREATE OR REPLACE FUNCTION` for the immutable trigger function.
- Keeps the existing trigger replacement and append-only semantics.

## Recovery instructions for the reported failure

1. Stop API, worker and trainer processes.
2. Replace the project files with release 1.49.1 while retaining the existing `.env` and PostgreSQL database.
3. Do **not** drop the two risk columns.
4. Do **not** run `alembic stamp`.
5. Run:

```powershell
python manage.py migrate
```

PostgreSQL transactional DDL leaves `alembic_version` at the last successfully committed revision after the reported failure. The guarded migration can therefore be rerun directly.

Optional verification before rerun:

```sql
SELECT version_num FROM alembic_version;
```

The expected value after the shown failure is `0005_plan_outcome_invalid_input`.

## Compatibility

- Version: 1.49.1 patch release.
- Alembic head: unchanged, `0017_model_artifact_blobs`.
- New migration: none.
- `.env` changes: none.
- API/UI/model artifact/risk-policy changes: none.
- Existing databases already at head do not rerun historical revisions and remain unchanged.
- Failed or clean installations can rerun `python manage.py migrate` without manual schema deletion.

## Verification

- Original regression on unmodified 1.49.0: failed at the first missing `IF NOT EXISTS` assertion, matching the operator's `DuplicateColumn` traceback.
- Patched targeted regression: passed.
- Alembic PostgreSQL offline SQL generation from base to head: passed.
- Full unit suite and static checks: see `docs/QA_REPORT.md`.
- Live PostgreSQL post-fix migration was not run in the build environment because no isolated PostgreSQL server/URL was available; the existing integration migration test remains the required operator-side confirmation.
