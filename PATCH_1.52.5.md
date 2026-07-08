# PATCH 1.52.5 — trainer legacy metrics profile wait diagnostics

## Problem

A successful bootstrap/recovery training attempt can end with `activation_skipped=quality_gate_failed` or a data-dependent walk-forward deferral while preserving the immutable training profile under candidate `metrics.training_data_profile` rather than under `trigger.training_data_profile`.

Before this patch the scheduler only read the previous profile from `JobRun.details.trigger`. When that trigger profile was absent but the same evidence existed in candidate metrics, the trainer could not classify the state as a data-dependent wait and fell back to generic `training_cooldown_not_elapsed`. That made the operator view less specific and could lead to unnecessary repeated bootstrap attempts after cooldown instead of a clear wait for new labeled timestamps.

## Change

- Added `app.workers.trainer._job_training_profile()` to resolve persisted previous profile evidence from:
  1. `trigger.training_data_profile`;
  2. `metrics.training_data_profile`.
- `BackgroundTrainer.due_reason()` now uses that helper for data-dependent bootstrap/recovery skips.
- Wait diagnostics include `previous_profile_source` so QA/operator diagnostics show which persisted evidence was used.
- Added regression coverage for legacy candidate-metrics-only profile evidence.

## Compatibility

- Database migrations: not required.
- `.env`: unchanged.
- API contract: unchanged.
- Model artifact schema: unchanged.
- Trainer quality gates, activation gates, cooldown durations and thresholds are unchanged.

## Verification

Targeted regression:

```bash
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py::test_rejected_bootstrap_recovers_profile_from_candidate_metrics
```

Red on unchanged 1.52.4 with the new test: `1 failed`, because the reason was `training_cooldown_not_elapsed` instead of `quality_gate_failed_waiting_for_new_data`.

Green after fix:

```bash
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py tests/unit/test_trainer_operator_ui.py
```

Result: `16 passed`.

Full available static/targeted post-check status is documented in `docs/QA_REPORT.md`.

## Limitations

If a prior job has no valid `TrainingDataProfile` in either trigger or metrics, the scheduler intentionally keeps the generic fail-closed cooldown; it cannot safely infer whether the current profile is unchanged.
