# Patch 1.25.0 — fail-closed model activation gate

## Problem

Model quality gates were enforced by the background trainer before automatic activation, but they were not enforced at the central activation mutation boundary:

- `scripts/train.py --activate` called `register_and_activate_model_candidate(..., quality_gate=None)`;
- `scripts/model_registry.py activate` validated artifact checksum/version/horizon but did not inspect the persisted `metrics.quality_gate`;
- `register_and_activate_model_candidate` accepted missing, failed or contradictory gate evidence.

An operator command could therefore activate a candidate that failed model-quality, temporal, policy-economics or incumbent-relative gates without any explicit emergency override. This was a silent safety-boundary bypass.

## Solution

- Added `require_passed_quality_gate` and activation schema `model-activation-quality-gate-v1`.
- Atomic candidate activation now fails before artifact validation or PostgreSQL mutation unless the gate is present, `passed=true`, and has an empty valid reason list.
- Manual training always evaluates the normal quality gate. `train --activate` registers a failed candidate inactive with `activation_requested=true` and leaves the incumbent unchanged.
- Registered-model activation now requires the persisted passed gate by default.
- Emergency rollback to a legacy/failed-gate version remains possible only with both:
  - `--emergency-gate-override`;
  - non-empty `--override-reason`.
- The original gate, override flag and reason are written into the `MODEL_ACTIVATED` audit payload.
- Artifact checksum, version, horizon and concurrent active-version checks remain unchanged.

## Compatibility

- No Alembic migration.
- No new `.env` variable.
- No model artifact schema change or retraining requirement.
- No policy/risk threshold change.
- Existing registered versions without passed gate evidence now require explicit emergency override for activation.
- The release archive restores the non-secret `.env.example` required by `manage.py setup`.

## Verification

Baseline 1.24.0:

```text
592 passed, 4 skipped, 61 warnings
```

Red evidence before implementation:

```text
6 failed
- atomic activation did not reject None/failed/contradictory gates
- registered failed model activated without an error
- no emergency override contract existed
- manual train attempted activation with quality_gate=None
```

Post-change focused verification:

```text
6 passed
43 passed  # activation/recovery/lifecycle focused group
```

Post-change full verification:

```text
598 passed, 4 skipped, 61 warnings
ruff: passed
compileall: passed
node --check: passed
alembic head: 0014_ui_exposure_ledger
```

PostgreSQL integration tests were not run because no isolated `TEST_DATABASE_URL` was supplied.
