# QA Report

Release: **1.35.3**

Date: **2026-07-06**
Scope: **trainer stale-candidate closure and active-artifact recovery**

## Environment

- Python: 3.13.5 in the same isolated virtual environment used for baseline and post-checks.
- Project requirement: Python >=3.12.
- Node syntax check: available.
- Separate PostgreSQL integration database: not configured.
- Input archive: `cost_aware_momentum-1.35.2-point-in-time-ticker.zip`.
- Input archive SHA-256: `9d77db0d19bc29ea845de6d6d9d1f27bd385d01be27be3612ffc8e6fea62c0ca`.
- Source version: 1.35.2.

## Baseline before changes

| Check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED: no broken project requirements in the isolated environment |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 709 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |

The seven skipped tests require an isolated PostgreSQL integration database.

## Confirmed defects

### 1. Permanent stale-candidate promotion block — high operational severity

`BackgroundTrainer.reconcile_pending_activation` returned `BLOCKED` for a quality-passed inactive candidate whose immutable `promotion_policy_binding` was missing/invalid. The candidate remained `activation_requested=true`, so every scheduling cycle selected the same unusable row and returned before `due_reason()`.

The operator state reproduced in release 1.35.2 was therefore internally consistent but deadlocked: active artifact missing, baseline fallback active, automatic experiment absent, and wait reason `candidate_policy_binding_missing_or_invalid`.

Because the binding is immutable evidence, waiting cannot repair it. The candidate must be terminally closed and a new governed candidate must be trained.

### 2. Candidate artifact was not checked before automatic experiment — high integrity severity

The trainer checked only that candidate SHA-256 metadata had length 64. A deleted artifact or a file whose bytes no longer matched the registry could reach automatic experiment orchestration. This wastes research runs and can leave another non-actionable pending candidate.

### 3. Recovery eligibility incorrectly depended on baseline fallback — high availability severity

`due_reason()` and operator `recovery_availability()` used a helper that returned a recovery notice only when baseline runtime fallback was allowed. In production, where inference correctly remains fail-closed, the same condition also disabled trainer recovery. A missing active artifact could therefore prevent both inference and governed rebuilding.

### 4. Scheduler stopped after terminal stale-candidate closure — medium operational severity

Even a terminal `REJECTED` promotion result caused an unconditional return. Recovery or the actual quality/data cooldown reason was deferred to a later loop instead of being evaluated in the same iteration.

## Red evidence

A pristine 1.35.2 tree was supplied with the seven new regression tests and executed with:

```bash
python -m pytest -q tests/unit/test_trainer_artifact_loss_recovery_2026_07_06.py
```

Result: **7 failed**.

Failures independently demonstrated:

- no production recovery trigger for a missing active artifact;
- operator recovery unavailable in fail-closed production;
- missing and hash-mismatched pending artifacts reaching experiment orchestration;
- scheduler not continuing after terminal closure;
- legacy candidate without policy binding remaining `BLOCKED` instead of being closed.

## Implemented correction

- Added a shared typed candidate artifact contract used before automatic experiment execution: path existence, hexadecimal SHA-256, byte-for-byte digest and deployment horizon.
- Converted irreparable candidate metadata/artifact failures to terminal rejection through `close_candidate_activation_request`; audit/outbox and original registry history remain intact.
- Marked stale-candidate terminal results with `continue_scheduling=true`; the scheduler proceeds immediately to `due_reason()`.
- Added `registry_artifact_recovery_notice`, which detects missing, unreadable, hash-invalid and hash-mismatched active artifacts independently of whether runtime baseline fallback is permitted.
- Applied the recovery notice to scheduled recovery, operator recovery, incumbent loading and activation-time recovery-condition recheck.
- Preserved fail-closed inference: production never loads baseline merely because recovery training is now allowed.
- Did not weaken model quality, walk-forward, policy, experiment-promotion or activation gates.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 716 passed, 7 skipped, 62 warnings |
| focused trainer/recovery/promotion suite | PASSED: 49 passed |
| new recovery regression file | PASSED: 7 passed |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |

## Interpretation of the operator screenshot

- `SUCCESS` means the training process completed and registered a candidate; it does **not** mean quality gate or activation succeeded.
- `walk_forward_policy_stability_below_minimum`, `holdout_span_below_minimum`, `policy_trade_rate_below_minimum` and `policy_independent_cohort_count_below_minimum` remain legitimate fail-closed quality reasons. Release 1.35.3 does not suppress them.
- After stale-candidate closure, the dialog should expose the actual remaining reason, normally `quality_gate_failed_waiting_for_new_data`, recovery cooldown, insufficient history, or a new training run.
- Missing active artifact remains a serious release/runtime integrity event; rebuilding a candidate does not guarantee it will pass quality gates.

## Not run / residual limitations

- PostgreSQL integration tests and `manage.py test --require-integration`: NOT RUN because no isolated `TEST_DATABASE_URL` was available.
- `manage.py doctor`: NOT RUN because this sandbox does not contain the operator's configured PostgreSQL/Bybit runtime.
- Actual cleanup of the user's existing pending candidate and audit/outbox rows: NOT RUN; it occurs after deploying 1.35.3 and the trainer's next scheduling cycle.
- Real Windows service restart and filesystem permission behavior: NOT RUN.
- Economic reasons for the failed quality gate require the exact candidate metrics and training-data profile from the operator database; no thresholds were relaxed.
- This release fixes lifecycle deadlock/recovery correctness and does not establish profitability.
