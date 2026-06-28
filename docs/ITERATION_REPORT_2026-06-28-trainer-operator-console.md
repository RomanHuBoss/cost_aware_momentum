# Iteration report — trainer operator console

Date: 2026-06-28
Release: 1.8.0

## 1. Input archive and baseline identity

- Input: `cost_aware_momentum-1.7.12-manual-fill-chronology.zip`
- Input SHA-256: `f3c9a7d74f2904c2250f5bfbdced36e3b120d06b58d71246309f8518d4736c5b`
- Source version: `1.7.12`
- Python requirement: `>=3.12`
- Alembic head: `0005_plan_outcome_invalid_input`
- Source inventory before changes: 66 production Python files, 20 test Python files, 25 documentation/source files, 4 web files and 5 migrations.
- Input/release tree contained no `.env`, credentials, real model artifact or database dump. Test execution created caches which are removed before packaging.

## 2. Iteration goal and acceptance criteria

After this iteration the operator must be able to understand the actual background trainer state and request a safe immediate check/recovery from the UI, while fitting remains in the separate trainer process and all data/model gates remain enforced.

Acceptance criteria:

1. A discoverable «Обучатель» button opens a dedicated dialog.
2. The dialog shows heartbeat freshness, phase, next check, exact wait reason, readiness progress, artifact/runtime state and the latest training result.
3. `CHECK_NOW` is authenticated, CSRF-protected, persisted and processed by the trainer without waiting for the normal scheduler interval.
4. `RECOVER_NOW` is available only for no active model, registry baseline or a physically missing recoverable artifact.
5. Recovery may bypass scheduler cooldown/backoff but not minimum history, coverage, temporal validation, model quality gates, activation guards or the single-training lock.
6. Offline/stale trainer and disabled auto-training fail closed with HTTP 409.
7. Existing recommendation, advisory-only, PostgreSQL-only and model-lifecycle behavior does not regress.

## 3. Sources read and affected data flow

Read before implementation:

- `README.md`, `CHANGELOG.md`, `PATCH_1.7.12.md`;
- `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`;
- `pyproject.toml`, `.env.example`;
- `app/workers/trainer.py`, `app/api/v1/status.py`, `app/api/v1/admin.py`, auth/CSRF dependencies, ORM job/heartbeat/audit/outbox models;
- `web/index.html`, `web/css/app.css`, `web/js/app.js`;
- existing model recovery/scheduler tests and the user-provided `status.json` example.

Changed flow:

```text
operator UI
  -> authenticated + CSRF POST /api/v1/admin/trainer-control
  -> PostgreSQL ops.job_runs + audit.events + ops.outbox_events
  -> separate trainer control poll
  -> normal scheduler evaluation or recovery evaluation
  -> existing training job/advisory lock/candidate/gates/activation
  -> heartbeat + status API + SSE/UI refresh
```

No model fitting, ingestion or inference was moved into FastAPI requests.

## 4. Baseline before changes

Isolated environment commands from project root:

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 139 passed, 3 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |

The three skipped tests require a separate PostgreSQL test database.

## 5. Confirmed gap and impact

### CONFIRMED GAP — operator trainer observability/control

Severity: **medium** operational/UX.

Evidence:

- `web/index.html` had no trainer dialog or trainer button.
- `web/js/app.js::loadStatus()` reduced all trainer details to one noninteractive string.
- Detailed heartbeat and wait data were present only in raw `/api/v1/status`.
- `app/workers/trainer.py::due_reason()` had no explicit operator recovery request and the API had no trainer-control mutation.
- The provided status example contained actionable values (`WAITING`, reason, `1/168` timestamps), but the UI did not expose them.

Expected behavior: the operator can see why the trainer is waiting and request an immediate, audited evaluation without editing `.env`, restarting the supervisor or bypassing safety gates.

Actual behavior: raw JSON inspection and process/config workarounds were required.

Existing tests did not cover a trainer operator UI/control contract.

## 6. Planned and actual diff

Production/API:

- `app/api/schemas.py` — typed control action request.
- `app/api/v1/admin.py` — authenticated/CSRF control endpoint and preconditions.
- `app/api/v1/status.py` — artifact existence, trainer control state and stable latest training/control jobs.
  It also selects the freshest worker/trainer heartbeat when old instances remain stored.
- `app/services/trainer_control.py` — heartbeat/recovery eligibility, deduplicated PostgreSQL enqueue and serializers.
- `app/workers/trainer.py` — two-second control polling, command claim/finish, safe forced recovery and heartbeat updates.

Frontend:

- `web/index.html` — top-bar button and dialog.
- `web/css/app.css` — responsive status/progress layout.
- `web/js/app.js` — wait-reason translation, progress, results, actions, SSE/poll refresh.

Tests:

- `tests/unit/test_trainer_operator_ui.py`.
- `tests/unit/test_trainer_operator_control.py`.
- `tests/unit/test_trainer_recovery_scheduling.py`.

Documentation/version:

- package/app version, README, changelog, patch notes, operator/architecture/security/incident/QA/compliance/traceability documentation and this report.

No migration, dependency or `.env` change was needed.

## 7. Red → green evidence

Before production implementation:

```text
python -m pytest -q \
  tests/unit/test_trainer_recovery_scheduling.py::test_operator_recovery_bypasses_recovery_backoff_without_bypassing_gates \
  tests/unit/test_trainer_recovery_scheduling.py::test_operator_recovery_does_not_bypass_minimum_history \
  tests/unit/test_trainer_operator_ui.py
```

RED:

```text
3 failed
```

Substantial reasons:

- `BackgroundTrainer.due_reason()` rejected `force_recovery`;
- no `trainer-button`, dialog or control endpoint existed.

After implementation the same selection passed:

```text
3 passed
```

Six additional control/status tests cover route security registration, artifact eligibility, heartbeat freshness, newest-instance selection and both command processing paths.

## 8. Migration, API, configuration and compatibility

- Alembic: unchanged, single head `0005_plan_outcome_invalid_input`.
- Storage: reuses `ops.job_runs`, `audit.events` and `ops.outbox_events`.
- API: backward-compatible extension of `/api/v1/status`; new POST endpoint only.
- Authentication: existing operator session/API token plus CSRF for browser mutation.
- `.env`: no new variables.
- Rollout: restart API and trainer. Worker can remain compatible, but restarting the local supervisor is recommended.
- Advisory-only and read-only Bybit boundaries unchanged.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 148 passed, 3 skipped, 19 warnings |
| targeted new trainer tests | PASSED — 9 tests |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |
| version consistency | PASSED — package/application `1.8.0` |

`python manage.py doctor` was executed with the isolated venv temporarily linked and failed for environmental reasons: `.env` absent, default secrets, `psql`/`pg_dump`/`pg_restore` absent and no PostgreSQL service on localhost.

`python manage.py test --require-integration` could not run because neither `POSTGRES_ADMIN_URL` nor `TEST_DATABASE_URL` was configured. No SQLite or fake application database was substituted.

## 10. Not verified

- Real PostgreSQL endpoint/queue/concurrent trainer integration.
- Full browser automation and visual screenshot testing.
- Windows service deployment of the updated trainer process.
- Long-running fitting progress, because the estimators do not provide a trustworthy incremental percentage.

## 11. Residual risks and limitations

- A control request is normally consumed within two seconds, but actual start still depends on trainer CPU scheduling and PostgreSQL availability.
- A process crash after claiming a control request can leave that request `RUNNING`; the latest heartbeat and job status expose this for incident handling, but automatic stale-command requeue is not implemented in this iteration.
- `CHECK_NOW` may legitimately return the same wait reason; it is not a command to weaken data thresholds.
- A recovery candidate can be trained and remain inactive when its quality gate fails.
- Technical correctness does not prove economic advantage or profitability.

## 12. Rollback

1. Stop API and trainer.
2. Restore the 1.7.12 source tree.
3. Restart processes.
4. No schema downgrade is required.
5. Existing `trainer_control_request` job/audit/outbox rows may remain as historical records; 1.7.12 ignores them.

## 13. Recommended next work package

Add a PostgreSQL integration test for control request enqueue/claim/deduplication and stale claimed-request recovery, then implement an explicit audited stale-command requeue policy. Do not combine it with ML or strategy changes.
