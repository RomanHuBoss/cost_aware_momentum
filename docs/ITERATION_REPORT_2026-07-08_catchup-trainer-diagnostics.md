# Iteration Report — 2026-07-08 — catch-up stale suppression and trainer diagnostics

## 1. Input archive

- Input ZIP: `/mnt/data/cost_aware_momentum-main.zip`.
- Input SHA-256: `9cbd4854ee0d342294f3a9f3bdb6ba70bf3af6261cc5c1e68c4458cceac9d44e`.
- Source version: 1.52.7.
- Target version: 1.52.8.
- Python requirement: `>=3.12`.
- Alembic head: `0018_inference_observations`.
- Migrations in tree: 18.
- Production Python files: 100.
- Test Python files before this iteration: 124; after this iteration: 125.
- Markdown documentation files before this iteration: 30; after this iteration: 32.
- Release boundary note: compile/test commands created transient caches during QA; they were removed before packaging.

## 2. Goal and acceptance criteria

Goal: after this iteration, stale catch-up inference is recorded once per `reason + event hour`, and the operator UI explains the observed trainer idle state from persisted training failure evidence when heartbeat has not yet published a `wait_reason`.

Acceptance criteria:

1. A first stale catch-up inference attempt still returns terminal `decision_publication_lag_exceeded` with publication-window diagnostics.
2. A repeated stale catch-up for the same `reason + event_time` returns `stale_catchup_inference_already_recorded` without running the job body again.
3. The next event hour is still eligible for a fresh stale-window classification.
4. `/api/v1/status` exposes an additive `trainer_control.effective_wait_reason` field.
5. Heartbeat `wait_reason` remains authoritative when present.
6. If heartbeat has no `wait_reason`, latest persisted `model_retraining` failure `No direction-specific barrier labels could be built from PostgreSQL candles` is classified as `no_direction_specific_barrier_labels`.
7. The UI consumes `effective_wait_reason` and no longer falls back to `Trainer еще не сообщил причину ожидания` for that observed failure.
8. No DB migration, order execution path, `.env` change, or gate weakening is introduced.

## 3. Read sources and data flow

Read sources:

- `README.md`, `CHANGELOG.md`, `PATCH_1.52.5.md`, `PATCH_1.52.6.md`, `PATCH_1.52.7.md`.
- `pyproject.toml`, `.env.example`.
- `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`.
- Worker flow: `app/workers/runner.py`.
- Trainer/status/UI flow: `app/workers/trainer.py`, `app/api/v1/status.py`, `web/js/app.js`, `web/index.html`.
- Relevant tests under `tests/unit`.

Data flow changed:

- Catch-up path: worker loop / startup → `Worker.catchup_inference_job(reason)` → stale publication-window check → terminal skip latch by `(reason, event_time)` → returned skip payload.
- Trainer diagnostics path: `ServiceHeartbeat.details.wait_reason` or latest `JobRun(job_name='model_retraining').details.error` → `/api/v1/status.trainer_control.effective_wait_reason` → `web/js/app.js::trainerWaitDescription` → operator dialog.

## 4. Baseline before code changes

Environment preparation note: the first baseline attempt showed missing declared project/dev tools `psycopg` and `ruff`. I installed declared dependencies `psycopg[binary,pool]` and `ruff` in the sandbox before modifying project code so the baseline suite could run.

Initial pre-dependency baseline:

| Command | Result |
|---|---|
| `python --version` | `Python 3.13.5`, exit 0 |
| `python -m pip check` | FAILED: external shared-env conflict `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED, exit 0 |
| `python -m ruff check .` | UNAVAILABLE: `No module named ruff` |
| `python -m pytest -q` | FAILED during collection: 61 import errors caused by missing declared dependency `psycopg` |
| `node --check web/js/app.js` | PASSED, exit 0 |

Runnable baseline after installing declared dependencies and before code changes:

| Command | Result |
|---|---|
| `python --version` | `Python 3.13.5`, exit 0 |
| `python -m pip check` | FAILED: same external `moviepy` / `pillow` shared-env conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED, exit 0 |
| `python -m ruff check .` | PASSED: `All checks passed!` |
| `python -m pytest -q` | PASSED: `863 passed, 8 skipped in 18.03s` |
| `node --check web/js/app.js` | PASSED, exit 0 |

`python manage.py doctor` and `python manage.py test --require-integration` were not part of the clean baseline because a project-local `.venv` and safe PostgreSQL integration DB were not configured.

## 5. Confirmed defects/gaps

### CONFIRMED DEFECT — repeated stale catch-up inference

- Files: `app/workers/runner.py`, `Worker.catchup_inference_job`.
- Evidence: 1.52.7 had `last_stale_hourly_decision_event_time` for hourly cycles, but no equivalent latch for catch-up inference. User logs showed repeated `Catch-up inference skipped because publication window is stale` for `event_time=2026-07-08T04:00:00+00:00` at `04:12:39` and `04:14:03`, both beyond `maximum_delay_seconds=600`.
- Expected: first stale catch-up records terminal skip; duplicate same-hour catch-up returns a suppression result without rerunning the job body.
- Actual: duplicate same-hour catch-up repeatedly returned full `decision_publication_lag_exceeded` and emitted another warning.
- Impact: operational noise and misleading evidence that the worker was still trying to publish stale signals.
- Severity: medium.
- Why existing tests missed it: 1.52.7 tested stale catch-up terminal blocking, but only hourly cycles had a repeated-stale suppression test.

### CONFIRMED GAP — trainer wait reason ignored latest persisted failure

- Files: `app/api/v1/status.py`, `web/js/app.js`.
- Evidence: UI rendered `Trainer еще не сообщил причину ожидания` from absent heartbeat `wait_reason`, while the same status payload showed latest training attempt `FAILED` with `No direction-specific barrier labels could be built from PostgreSQL candles`.
- Expected: UI explains that latest training failed because direction-specific labels could not be built from PostgreSQL candles, while keeping the baseline active as a fallback/runtime state.
- Actual: operator had to infer the cause manually from the separate last-attempt section.
- Impact: diagnostics/UX gap during bootstrap recovery; could lead to unnecessary manual intervention or gate weakening.
- Severity: medium.
- Why existing tests missed it: UI tests asserted presence of known wait reason strings, but not derived reasons from latest `JobRun` when heartbeat `wait_reason` is absent.

## 6. Plan and actual diff

Production files:

- `app/workers/runner.py`: added `last_stale_catchup_inference_key` latch and duplicate stale catch-up suppression.
- `app/api/v1/status.py`: added `trainer_effective_wait_reason()` and `trainer_control.effective_wait_reason` payload.
- `web/js/app.js`: UI consumes `effective_wait_reason`; added labels and summary states for label-building failures and generic failed-training retry waits.
- `app/__init__.py`, `pyproject.toml`: version 1.52.8.

Tests:

- `tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py`: repeated stale catch-up regression.
- `tests/unit/test_trainer_status_diagnostics_2026_07_08.py`: effective wait reason helper tests.
- `tests/unit/test_trainer_operator_ui.py`: UI string/contract coverage.

Docs:

- `README.md`, `CHANGELOG.md`, `PATCH_1.52.8.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/OPERATOR_MANUAL.md`, this report.

Migrations/config/API compatibility:

- No migration.
- No `.env` change.
- API change is additive only: `trainer_control.effective_wait_reason`.
- No Bybit order create/amend/cancel code added.

## 7. Red → green evidence

Red on 1.52.7 after adding the new tests:

```bash
python -m pytest -q \
  tests/unit/test_trainer_status_diagnostics_2026_07_08.py \
  tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py::test_repeated_stale_catchup_is_suppressed_until_next_event_hour \
  tests/unit/test_trainer_operator_ui.py
```

Red result: collection interrupted because `trainer_effective_wait_reason` did not exist in 1.52.7.

Additional isolated red evidence:

```bash
python -m pytest -q tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py::test_repeated_stale_catchup_is_suppressed_until_next_event_hour
```

Result: `1 failed`; the second catch-up attempt returned another `decision_publication_lag_exceeded` instead of `stale_catchup_inference_already_recorded`.

```bash
python -m pytest -q tests/unit/test_trainer_operator_ui.py
```

Result: `1 failed`; `no_direction_specific_barrier_labels` was absent from `web/js/app.js`.

Green after fix:

```bash
python -m pytest -q \
  tests/unit/test_trainer_status_diagnostics_2026_07_08.py \
  tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py::test_repeated_stale_catchup_is_suppressed_until_next_event_hour \
  tests/unit/test_trainer_operator_ui.py
```

Result: `4 passed in 4.09s`.

## 8. Migration/API/config compatibility

- Alembic head remains `0018_inference_observations`.
- No migration files added.
- No settings or `.env.example` changes.
- `/api/v1/status` payload is backward-compatible/additive.
- Existing clients that ignore `trainer_control.effective_wait_reason` continue to work.

## 9. Post-check

| Command | Result |
|---|---|
| `python --version` | `Python 3.13.5`, exit 0 |
| `python -m pip check` | FAILED: external shared-env conflict `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0`; unrelated to project diff |
| `python -m compileall -q app scripts tests manage.py` | PASSED, exit 0 |
| `python -m ruff check .` | PASSED: `All checks passed!` |
| `python -m pytest -q` | PASSED: `866 passed, 8 skipped in 18.13s` |
| `node --check web/js/app.js` | PASSED, exit 0 |
| `python -m alembic heads` | PASSED: `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment precondition: project-local `.venv` not present; command prints `Виртуальная среда не найдена. Сначала выполните: python manage.py setup` |
| `python manage.py test --require-integration` | FAILED / environment precondition: project-local `.venv` not present before integration dispatch |

## 10. Not verified

- PostgreSQL integration upgrade/test cycle was not run because no safe separate `TEST_DATABASE_URL` was configured and `manage.py` requires a local project `.venv` in this sandbox.
- Live/read-only Bybit smoke was not run.
- Economic edge/profitability is not claimed.
- The actual production database still needs enough point-in-time market context to build direction-specific labels; this patch improves diagnostics and retry noise, not the underlying market-data availability.

## 11. Residual risks

- If market data remains incomplete, trainer will continue to fail or defer safely until backfill/funding/mark/index/OI/spec context becomes sufficient.
- `effective_wait_reason` is derived from persisted error strings for the known label-building failure. Unknown future failures are classified generically as `last_training_failed_waiting_for_retry`.
- Suppressing duplicate catch-up stale logs may reduce log volume for repeated symptoms; the first terminal skip still includes exact diagnostics.

## 12. Rollback procedure

1. Stop API/UI, worker and trainer.
2. Restore the previous 1.52.7 tree/archive.
3. Restart services.
4. No database downgrade is required because no migration was added.
5. If rolling back only code, clear browser cache/reload UI assets so `web/js/app.js` matches the backend.

## 13. Recommended next work package

Investigate why the current PostgreSQL training slice cannot produce direction-specific barrier labels: add a preflight label-building attrition report that counts candles removed by missing mark/index/OI/funding/spec context, invalid OHLC, horizon truncation, and barrier construction filters before `build_model_candidate()` raises.
