# Patch 1.35.3 — trainer recovery deadlock

## Problem

Release 1.35.2 could remain indefinitely in the operator-visible state:

- trained registry version exists but its active artifact is missing;
- runtime uses controlled baseline fallback in paper/shadow mode;
- a prior inactive candidate remains `activation_requested=true`;
- that candidate lacks the current immutable deployment-policy binding, or its artifact is missing/corrupt;
- `reconcile_pending_activation()` returns `BLOCKED` each cycle and scheduler never reaches `due_reason()`.

In production the recovery trigger had an additional defect: recovery eligibility reused the baseline-fallback helper. Since production correctly forbids baseline fallback, it also incorrectly disabled governed recovery training.

## Correction

- Introduced `registry_artifact_recovery_notice` for missing, unreadable, invalid-SHA and hash-mismatched active artifacts, independent of runtime fallback permissions.
- Promoted the automatic-experiment artifact checker to the shared typed `candidate_artifact_contract`.
- Candidate artifact/horizon validation now runs before automatic experiment orchestration.
- Immutable invalid candidate states are terminally closed through `close_candidate_activation_request` with audit/outbox evidence.
- Missing/invalid policy binding is terminal, not an endlessly repairable wait state.
- Scheduler continues in the same iteration after stale-candidate closure.
- Incumbent loading and activation recovery-condition recheck use the same recovery contract.

## Compatibility

- No PostgreSQL migration.
- No `.env` changes.
- No active artifact schema change.
- No threshold, cost, risk, walk-forward, quality or experiment gate change.
- Existing active artifact continues normally when its file and SHA-256 are valid.
- Existing malformed pending candidates are not deleted; only their activation request is terminally closed and the rejection is audited.

## Validation

Baseline: `709 passed, 7 skipped, 62 warnings`.

New tests on pristine 1.35.2: `7 failed`.

Post-change: `716 passed, 7 skipped, 62 warnings`; focused trainer/recovery/promotion suite `49 passed`.

PostgreSQL integration tests were not run because no isolated `TEST_DATABASE_URL` was available.

## Operator action

1. Replace the project with release 1.35.3.
2. Restart trainer and API; restart inference worker as well if the active artifact is missing.
3. Open the trainer dialog and press **Обновить состояние** after the next scheduler cycle.
4. A stale candidate should be closed automatically. The displayed wait reason should change to the actual remaining state.
5. Do not relax quality gates merely to activate the candidate. The gate reasons from the last attempt require more/more suitable data or model/policy correction.
