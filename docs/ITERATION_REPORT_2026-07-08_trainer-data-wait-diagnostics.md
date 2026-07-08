# Iteration report — trainer data wait diagnostics

Date: 2026-07-08.

## 1. Input archive

- Input ZIP: `cost_aware_momentum-1.52.3-stale-decision-publication.zip`.
- Input SHA-256: `21c5a98eb5a217c1d4eeb5a4fb7c0e7a8721ac4314e6f782bb84431e91239703`.
- Input version: 1.52.3.
- Output version: 1.52.4.
- Alembic head: `0018_inference_observations`.

## 2. Goal and acceptance criteria

Goal: after this iteration, a running background trainer with only `baseline-momentum-v1` active must explain data-dependent rejected-candidate waits directly, instead of hiding them behind a generic cooldown message.

Acceptance criteria:

1. A rejected bootstrap/recovery candidate with `activation_skipped=quality_gate_failed` and no new training data returns `quality_gate_failed_waiting_for_new_data` even during the configured cooldown.
2. A data-dependent walk-forward deferral returns `training_deferred_waiting_for_new_data` with the same new-data progress semantics.
3. Generic cooldown remains available for normal retry throttling and cases without previous training profile evidence.
4. UI renders human-readable Russian messages and progress for both data-dependent wait reasons.
5. Trainer gates, quality thresholds and cooldown limits are not weakened.
6. Full unit/static checks pass in the reproducible dependency set.

## 3. Sources read and data flow

Read sources:

- `README.md`, `CHANGELOG.md`, `PATCH_1.52.1.md`–`PATCH_1.52.3.md`.
- `pyproject.toml`.
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/OPERATOR_MANUAL.md`.
- `app/workers/trainer.py`.
- `web/js/app.js`.
- `tests/unit/test_trainer_recovery_scheduling.py`.
- `tests/unit/test_trainer_operator_ui.py`.

Data flow:

`JobRun(model_retraining).details.activation_skipped + trigger.training_data_profile` → `BackgroundTrainer.due_reason()` → `ServiceHeartbeat.details.wait_reason` → `/api/v1/status` → `web/js/app.js::trainerWaitDescription()` → operator trainer dialog.

## 4. Baseline

Baseline on unchanged 1.52.3 with NumPy 2.3.5 / pandas 2.2.3 / scikit-learn 1.7.2:

| Command | Result |
|---|---|
| `python --version` | Python 3.13.5 |
| `python -m pip check` | PASSED, no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED, 857 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED, `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment limitation: `.env` absent, default secrets, no local PostgreSQL/tools |
| `python manage.py test --require-integration` | NOT RUN: no safe `TEST_DATABASE_URL` |

Fresh install risk before the dependency-bound change: with NumPy 2.5.1 allowed by the old `numpy>=2.1,<3` constraint, the existing suite failed with `10 failed, 847 passed, 8 skipped` in funding replay and policy phase tests. This was treated as dependency contract hardening, not as a new econometric implementation in this iteration.

## 5. Confirmed defects/gaps

### CONFIRMED DEFECT — generic cooldown hides true trainer wait reason

- File: `app/workers/trainer.py`, `BackgroundTrainer.due_reason()`.
- Severity: medium operational / high diagnostics for bootstrap recovery.
- Evidence: for same bootstrap episode, `activation_skipped=quality_gate_failed`, previous profile present and `new_timestamps=0`, unchanged 1.52.3 returned `training_cooldown_not_elapsed` during the 6-hour cooldown.
- Expected: report that the previous candidate failed quality gate and trainer is waiting for new labeled data, while preserving cooldown metadata.
- Impact: operator sees baseline active and believes trainer is merely idle until a timestamp, without seeing that immediate retraining is unlikely to help until new evidence exists.
- Why tests missed it: existing tests covered the post-cooldown new-data wait and a no-profile cooldown case, but not the profile-backed wait during cooldown.

### CONFIRMED GAP — UI lacked labels for data-dependent trainer waits

- File: `web/js/app.js`.
- Severity: medium UX/diagnostics.
- Evidence: `trainerWaitLabels` did not include `quality_gate_failed_waiting_for_new_data` or `training_deferred_waiting_for_new_data`; progress rendering only covered generic new-data reasons and pending triggers.

### CONFIRMED DEFECT — dependency constraint allowed incompatible NumPy 2.5.1

- File: `pyproject.toml`.
- Severity: medium QA reproducibility.
- Evidence: old `numpy>=2.1,<3` allowed NumPy 2.5.1; full suite failed on existing funding replay and policy phase contracts. NumPy 2.3.5 passes the same suite.

## 6. Plan and actual diff

Production:

- `app/workers/trainer.py`: classify data-dependent rejected bootstrap/recovery waits before generic cooldown when previous profile evidence proves no sufficient new data.
- `web/js/app.js`: add labels and progress rendering for the explicit wait reasons.
- `pyproject.toml`: constrain NumPy to `<2.5`.

Tests:

- `tests/unit/test_trainer_recovery_scheduling.py`: add red→green regression for quality-gate rejected bootstrap during cooldown.
- `tests/unit/test_trainer_operator_ui.py`: assert UI knows both data-dependent wait labels.

Docs/release:

- `app/__init__.py`, `README.md`, `CHANGELOG.md`, `PATCH_1.52.4.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/OPERATOR_MANUAL.md`, this report, `SHA256SUMS`.

No migrations, API changes, env changes or model-artifact changes.

## 7. Red → green evidence

Red command on unchanged 1.52.3 production code with the new regression test copied in:

```bash
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py::test_rejected_bootstrap_reports_new_data_wait_even_during_cooldown
```

Red result: `1 failed`.

Essential failure:

```text
AssertionError: assert 'training_cooldown_not_elapsed' == 'quality_gate_failed_waiting_for_new_data'
```

Green after fix:

```bash
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py tests/unit/test_trainer_operator_ui.py
```

Green result: `15 passed`.

## 8. Migration/API/config compatibility

- Alembic migration: not required.
- API contract: unchanged.
- `.env`: unchanged.
- Dependency contract: NumPy is now `>=2.1,<2.5` for reproducible QA.
- Rollback risk: if an environment intentionally used NumPy 2.5.x, it must downgrade until the funding/policy code is adapted and tested for NumPy 2.5+ semantics.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | PASSED, no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED, 858 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED, `0018_inference_observations (head)` |
| `python -B manage.py release-check --write` | PASSED |
| `python -B manage.py release-check` | PASSED |

`python manage.py doctor` failed only because this sandbox has no local `.env`, non-default secrets, PostgreSQL server or PostgreSQL CLI tools. `python manage.py test --require-integration` was not run because no safe separate PostgreSQL test database was configured.

## 10. Not verified

- PostgreSQL integration suite.
- Live Bybit read-only smoke.
- Actual trainer run against the user's database.
- Economic profitability / forward performance.

## 11. Residual risks

- If the previous training job lacks `trigger.training_data_profile`, the trainer still falls back to generic cooldown because it cannot prove the no-new-data condition safely.
- `quality_gate_failed_waiting_for_new_data` does not mean future training will pass; it only states why the current repeat is not started.
- NumPy 2.5+ support remains a separate future compatibility work package.

## 12. Rollback

To rollback, restore release 1.52.3, reinstall dependencies by its `pyproject.toml`, and restart trainer/API. No DB downgrade is required.

## 13. Recommended next work package

Implement and test explicit NumPy 2.5+ compatibility for historical funding replay and policy phase uncertainty, then relax the dependency upper bound only after full suite green under both old and new NumPy series.
