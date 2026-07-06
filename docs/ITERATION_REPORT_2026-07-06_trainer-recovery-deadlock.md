# Iteration report — trainer recovery deadlock

## 1. Input

- Archive: `cost_aware_momentum-1.35.2-point-in-time-ticker.zip`
- SHA-256: `9d77db0d19bc29ea845de6d6d9d1f27bd385d01be27be3612ffc8e6fea62c0ca`
- Source version: 1.35.2
- Target version: 1.35.3
- Date: 2026-07-06

## 2. Goal and acceptance criteria

After this iteration an immutable unusable pending candidate must not permanently prevent the trainer from evaluating active-artifact recovery or current data readiness.

Acceptance criteria:

1. Missing/hash-mismatched candidate artifact is rejected before automatic experiment.
2. Missing/invalid immutable policy binding terminally closes the candidate activation request.
3. Closure preserves audit/outbox history and does not activate anything.
4. Scheduler continues to `due_reason()` in the same iteration for this stale-candidate class.
5. Missing active artifact triggers governed recovery even when production runtime fallback is forbidden.
6. Inference baseline policy and all model/policy/activation gates remain unchanged.
7. Full unit suite and static checks remain green.

## 3. Sources and data flow

Read: README, CHANGELOG, patches 1.34.0–1.35.2, QA/SPEC_COMPLIANCE/TRACEABILITY, trainer worker, runtime selection, trainer control, automatic experiment and model-promotion services, and associated unit tests.

Affected flow:

`ModelRegistry pending candidate → candidate artifact/policy validation → terminal closure or experiment gate → scheduler continuation → active ModelRegistry artifact recovery notice → due_reason/operator recovery → governed training → candidate registration/activation gates`.

## 4. Baseline

- Python 3.13.5.
- `pip check`: passed in isolated project environment.
- `compileall`: passed.
- Ruff: passed.
- Pytest: 709 passed, 7 skipped, 62 warnings.
- JavaScript syntax: passed.
- Alembic: one head `0016_universe_replay_asof`.

## 5. Confirmed defects

### High — immutable candidate deadlock

`reconcile_pending_activation()` treated missing/invalid `promotion_policy_binding` as `BLOCKED`. The candidate remained pending and was selected forever. The screenshot's `candidate_policy_binding_missing_or_invalid` state is a direct manifestation.

### High — experiment before artifact integrity validation

Only SHA metadata length was checked. Deleted or hash-mismatched bytes could enter experiment orchestration.

### High — production recovery coupled to fallback

The recovery helper returned a notice only when baseline fallback was allowed. Production therefore had neither runtime fallback nor a trainer recovery trigger.

### Medium — terminal closure delayed actual scheduling

The scheduler returned for all `REJECTED` promotion results, even when the unusable candidate had just been terminally closed.

## 6. Plan and diff

Production:

- `app/ml/runtime_selection.py`: recovery-only artifact notice independent of fallback.
- `app/services/automatic_experiment.py`: typed reusable candidate artifact contract.
- `app/services/trainer_control.py`: operator recovery uses recovery notice.
- `app/workers/trainer.py`: pre-experiment candidate validation, terminal closure, scheduler continuation, recovery contract in scheduled training.

Tests:

- new `tests/unit/test_trainer_artifact_loss_recovery_2026_07_06.py`;
- unrelated promotion/orchestration tests explicitly bypass the new artifact prerequisite in their focused test doubles.

No migration or environment changes.

## 7. Red → green evidence

On pristine 1.35.2 with the seven new regression tests:

```text
7 failed
```

On corrected code:

```text
7 passed
```

The broader focused trainer/recovery/promotion set passed 48 tests.

## 8. Compatibility

- DB schema unchanged.
- API schema unchanged.
- `.env` unchanged.
- Active artifact bundle contract unchanged.
- Candidate records remain immutable except for the existing terminal activation-request closure fields.
- Advisory-only and PostgreSQL-only boundaries preserved.

## 9. Post-check

- `python -m pip check`: passed.
- `python -m compileall -q app scripts tests manage.py`: passed.
- `python -m ruff check .`: passed.
- `python -m pytest -q`: 716 passed, 7 skipped, 62 warnings.
- `node --check web/js/app.js`: passed.
- Alembic heads: one.

## 10. Not verified

- Isolated PostgreSQL integration suite.
- Actual mutation of the user's existing candidate row after deployment.
- Windows service/filesystem recovery behavior.
- Exact quality metrics behind the failed candidate in the user's database.
- Forward profitability.

## 11. Residual risks

A replacement candidate can still fail the same quality gates. This is intended. Repeated training on unchanged data is cooldown-controlled and cannot convert insufficient holdout span, low trade density, weak walk-forward stability or too few independent cohorts into valid evidence.

## 12. Rollback

Stop trainer/API/worker, restore release 1.35.2, and restart. No DB rollback is necessary. A candidate terminally closed by 1.35.3 should not be manually reopened; rollback does not reverse append-only audit/outbox evidence.

## 13. Recommended next work package

Read-only diagnostics for the exact quality-gate metrics behind `walk_forward_policy_stability_below_minimum`, `holdout_span_below_minimum`, low policy trade rate and insufficient independent cohorts, including observed values, required values and the earliest data time at which each temporal gate can become satisfiable. Do not lower the gates without that evidence.
