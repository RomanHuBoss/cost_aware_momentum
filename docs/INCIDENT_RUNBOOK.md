# Incident runbook

## Scope

This runbook covers fail-closed incidents in the local advisory system. It does not authorize order placement, modification, cancellation or withdrawal.

## Immediate containment

1. Stop using affected recommendations; do not copy quantities or levels manually from stale screenshots.
2. Preserve PostgreSQL, application logs, audit/outbox rows and the exact application/model versions.
3. Do not edit plan snapshots, account snapshots or audit-chain rows in place.
4. Keep the current active model unless artifact validation itself is the incident; a failed candidate must not deactivate the incumbent.

## `INVALID_SNAPSHOT` execution economics

- Treat all displayed plan economics as unavailable; signal economics remains a separate reference only.
- Recalculate the plan from the active profile and fresh market/account data.
- Compare `entry_price`, `planning_time`, costs and stored core values in `sizing_snapshot` with the audit event.
- If recalculation repeats the incident, stop API/worker, restore the last verified release/database backup in an isolated environment and open a defect with the immutable snapshot payload redacted of credentials.

## Invalid read-only profile or missing account link

- Confirm profile mode is exactly `bybit_read_only` and `source_account_id` matches the intended read-only account identifier.
- Confirm the Bybit key has read-only permissions and the matching account snapshot is fresh.
- Never change the profile to `manual` merely to bypass the block. Create/review an intentional manual profile separately when that is operationally appropriate.

## Stale/missing market or account data

- Verify worker heartbeat, API reachability, clock synchronization and PostgreSQL health.
- Confirm source timestamps are timezone-aware and not in the future.
- Resume recommendation use only after a fresh snapshot and a new plan version are produced.

## Model artifact incident

- Do not overwrite the active artifact.
- Validate SHA-256, task, schema, classes, horizon and registry state.
- Use documented activation/rollback commands only after the candidate/incumbent gates and audit trail are reviewed.

## Database or audit incident

- Stop writers, preserve evidence and verify backup restore in a disposable PostgreSQL database.
- Do not use SQLite or `create_all` as a recovery shortcut.
- Verify Alembic has one expected head before returning the service to advisory use.

## Return-to-service criteria

- Root cause is documented; affected state is replaced by a new immutable version rather than edited.
- `doctor`, static checks, unit tests and safe PostgreSQL integration tests pass in the target environment.
- Release checksum verification passes and no secrets/runtime artifacts are present in the release tree.
- Operator reviews the first new plan and confirms signal/plan economics scopes, timestamps and blocking diagnostics.
