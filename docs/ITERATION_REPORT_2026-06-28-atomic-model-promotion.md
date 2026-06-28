# Iteration report — atomic model candidate promotion

Date: 2026-06-28
Release: 1.7.8

## 1. Input archive and starting state

- Input: `cost_aware_momentum-main.zip`
- Input SHA-256: `df0cbffd190fd0d7575aab141c848b1c1bdfede03998ecd060d422c382bf02d5`
- Starting version: `1.7.7`
- Python requirement: `>=3.12`
- Observed host Python: `3.13.5`
- Alembic head: `0005_plan_outcome_invalid_input`
- Production/support files under `app`, `scripts`, `web`, `migrations`: 77
- Test files: 18 before this iteration
- Documentation files: 20 before this iteration
- Input release artifacts requiring exclusion from the new ZIP: `cost_aware_momentum.egg-info/` and stale `SHA256SUMS`.

## 2. Goal and acceptance criteria

Goal:

> After this iteration, creation and activation of a new model candidate must be one atomic PostgreSQL operation, proven by rollback and concurrency-guard tests.

Acceptance criteria:

1. A new gate-passed candidate and its activation use one transaction.
2. Candidate and activation audit/outbox events are written inside that same transaction.
3. Failure during activation audit rolls back the candidate registration rather than leaving a partial registry state.
4. A changed active version is detected before candidate insertion.
5. Failed/manual-review candidates remain inactive and use the existing registration path.
6. Background trainer, manual `train --activate` and gate-passed orphan recovery use the atomic operation.
7. No migration, API or `.env` change is introduced.
8. Full available checks remain green.

## 3. Sources read and data flow

Read before editing:

- `README.md`, `CHANGELOG.md`, `PATCH_1.7.4.md`–`PATCH_1.7.7.md`;
- `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- model lifecycle, trainer, registry CLI, manual training CLI and their tests.

Changed flow:

```text
trained immutable artifact
  -> SHA256/runtime metadata validation
  -> lock current active registry row
  -> verify expected incumbent version
  -> insert inactive candidate + candidate audit/outbox
  -> deactivate incumbent + activate candidate
  -> activation audit/outbox
  -> one transaction commit
```

If any database/audit/outbox step raises, the single transaction rolls back. Artifact fitting and file creation remain outside the database transaction.

## 4. Baseline before changes

### Host environment

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED (host environment) | external MoviePy/Pillow version conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no output |
| `python -m ruff check .` | UNAVAILABLE | Ruff not installed in host interpreter |
| `python -m pytest -q` | FAILED (host environment) | 7 collection errors because `psycopg` was absent |
| `node --check web/js/app.js` | PASSED | no output |

### Isolated project environment

An external temporary virtual environment was installed from `.[dev]`; it is not included in the release.

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no output |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 126 passed, 3 skipped, 20 warnings |
| `python -m alembic heads` | PASSED | `0005_plan_outcome_invalid_input` |
| release ZIP / re-extracted checks | PASSED | one root directory, no banned artifacts, full suite 129 passed / 3 skipped |
| `python manage.py doctor` | FAILED (environment) | project-local `.venv` not present; application `.env`/PostgreSQL were not configured |
| `python manage.py test --require-integration` | NOT RUN | no isolated PostgreSQL test database / `TEST_DATABASE_URL` |

## 5. Confirmed defect

### CONFIRMED DEFECT — non-atomic new-candidate promotion

- Severity: high operational/model-lifecycle correctness.
- Affected paths: `app/workers/trainer.py`, `scripts/train.py`, `scripts/model_registry.py`.
- Root contract: `app/ml/lifecycle.register_model_candidate()` committed before `scripts.model_registry.activate_registered_model()` opened a second transaction.
- Actual behavior: a candidate could be durably registered with `activation_requested=true`, while activation/audit/outbox failed afterward.
- Expected behavior: a new candidate intended for immediate activation should either be fully registered and active with both audit/outbox event pairs, or not be registered at all.
- Impact: stale incumbent remains active; candidate state is misleading; automatic pipeline result is incomplete; operator recovery is required.
- Why tests missed it: prior recovery tests mocked registration and activation as independent successful calls. No test observed transaction count or rollback after the candidate event was created.

This defect is proven structurally by the two separate `session.begin()` scopes and by the RED test below. No production database was modified.

## 6. Plan and actual diff

Production changes:

- `app/ml/lifecycle.py`: reusable in-session candidate insertion and atomic register+activate service.
- `app/workers/trainer.py`: uses atomic service only when auto-activation is permitted; failed gates remain standalone inactive registration.
- `scripts/train.py`: `--activate` uses atomic service while preserving default-horizon validation.
- `scripts/model_registry.py`: new gate-passed orphan recovery uses atomic service; already registered candidate resume remains explicit activation.

Tests:

- `tests/unit/test_atomic_model_promotion.py`: single transaction, rollback and concurrent incumbent change.
- `tests/unit/test_model_artifact_recovery.py`: updated recovery contract to assert use of the atomic service.

Documentation/version:

- `pyproject.toml`, `app/__init__.py`, `README.md`, `CHANGELOG.md`, `PATCH_1.7.8.md`;
- `docs/ARCHITECTURE.md`, `MODEL_CARD.md`, `OPERATOR_MANUAL.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`;
- this report.

No migration, dependency or `.env` change.

## 7. Red → green evidence

RED command on the pre-fix production code after adding the regression test:

```bash
python -m pytest -q tests/unit/test_atomic_model_promotion.py
```

Result: collection error — `ImportError: cannot import name 'register_and_activate_model_candidate' from 'app.ml.lifecycle'`.

GREEN targeted checks after implementation:

```bash
python -m pytest -q tests/unit/test_atomic_model_promotion.py
```

Result: 3 passed.

The tests independently assert:

- exactly one transaction context for registration and activation;
- both candidate and activation audit/outbox callbacks execute while that transaction is active;
- simulated activation-audit failure marks the transaction rolled back and not committed;
- active-version mismatch occurs before any candidate object is added.

## 8. Migration, API, configuration and compatibility

- Version: patch `1.7.8`.
- Alembic migration: none; head stays `0005_plan_outcome_invalid_input`.
- `.env`: no additions or changes.
- REST/frontend contract: unchanged.
- Existing inactive candidates: unchanged.
- Manual activation/rollback of already registered versions: unchanged.
- New candidate immediate activation: intentionally changes from two commits to one commit.
- Advisory-only and read-only Bybit boundaries: unchanged.

## 9. Post-check

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no output |
| `python -m ruff check .` | PASSED | All checks passed |
| `python -m pytest -q` | PASSED | 129 passed, 3 skipped, 20 warnings |
| targeted atomic/lifecycle/recovery tests | PASSED | 14 passed |
| `node --check web/js/app.js` | PASSED | no output |
| `python -m alembic heads` | PASSED | `0005_plan_outcome_invalid_input` |
| forbidden Bybit order-mutation scan | PASSED | no create/amend/cancel endpoint or method found |
| modified-file trailing-whitespace scan | PASSED | no matches |
| `python manage.py doctor` | FAILED (environment) | project-local `.venv` not present; application `.env` and PostgreSQL were not configured |
| PostgreSQL integration | NOT RUN | no isolated `TEST_DATABASE_URL` / test server |

No previously green unit test regressed. The three PostgreSQL integration tests remained correctly skipped in the ordinary suite.

## 10. Not verified

- Real PostgreSQL transaction rollback and row locking on PostgreSQL 16/17 were not executed because no isolated test database was available.
- No concurrent multi-process trainer test against a real database was run.
- Browser smoke test was not required because no API/frontend contract changed; JavaScript syntax was checked.
- No paper/shadow profitability claim is made.

## 11. Residual risks and limitations

- PostgreSQL integration remains necessary to prove actual `FOR UPDATE`, unique partial index and audit advisory-lock behavior under concurrency.
- Activation of an already registered candidate is still a separate explicit transaction by design; this patch covers creation plus immediate activation of a new candidate.
- A process crash after artifact file creation but before the atomic database transaction can still leave an orphan file; the 1.7.7 recovery command remains the intended path.
- Multi-fold walk-forward, drift monitoring and forward evidence remain outside this iteration.

## 12. Rollback procedure

1. Stop API, worker and trainer processes.
2. Restore source release 1.7.7.
3. No migration downgrade and no `.env` rollback are required.
4. Keep any registry/audit rows already committed by 1.7.8; they use the unchanged schema.
5. Restart processes and verify active model/runtime status.

Rollback reintroduces the two-transaction promotion window.

## 13. Recommended next work package

Add PostgreSQL integration coverage for concurrent model promotion and audit/outbox rollback using a dedicated temporary database, including two competing candidates and expected active-version guards. This should be implemented only when an isolated PostgreSQL test environment is available.
