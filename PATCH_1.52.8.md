# Patch 1.52.8 — catch-up stale suppression and trainer failure diagnostics

Date: 2026-07-08

## Problem

User runtime evidence showed two operator-facing defects:

1. `Catch-up inference skipped because publication window is stale` repeated for the same current-hour event after the decision publication window had already exceeded `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS=600`.
2. The trainer dialog said `Trainer еще не сообщил причину ожидания` while `/api/v1/status` already exposed the latest `model_retraining` attempt as failed with `No direction-specific barrier labels could be built from PostgreSQL candles`.

Both behaviours were noisy/ambiguous diagnostics defects. They did not justify publishing stale signals, weakening ML gates, activating baseline as a trained model, or changing retry limits.

## Solution

- `Worker.catchup_inference_job()` now records `last_stale_catchup_inference_key=(reason, event_time)` after a terminal stale publication skip and suppresses duplicate catch-up attempts for the same key until the next event hour.
- `/api/v1/status` now exposes `trainer_control.effective_wait_reason`.
  - Heartbeat `details.wait_reason` remains authoritative.
  - If heartbeat has no wait reason, the API derives a safe operator-facing reason from heartbeat `last_result` or the latest persisted `model_retraining` job error.
  - The known label-building failure is classified as `no_direction_specific_barrier_labels`.
- `web/js/app.js` consumes `effective_wait_reason`, updates the summary line, and shows explicit UI text for direction-specific label-building failures and generic failed-training retry waits.

## Tests

Added/updated regression coverage:

- `tests/unit/test_stale_decision_publication_scheduling_2026_07_08.py::test_repeated_stale_catchup_is_suppressed_until_next_event_hour`
- `tests/unit/test_trainer_status_diagnostics_2026_07_08.py`
- `tests/unit/test_trainer_operator_ui.py`

Red evidence on 1.52.7 with new tests:

- `trainer_effective_wait_reason` import failed because the API helper did not exist.
- Duplicate stale catch-up returned another full `decision_publication_lag_exceeded` result instead of `stale_catchup_inference_already_recorded`.
- UI test failed because `no_direction_specific_barrier_labels` / `effective_wait_reason` were absent.

Green evidence after fix:

```text
4 passed
```

Full post-check:

```text
python -m pytest -q: 866 passed, 8 skipped
node --check web/js/app.js: passed
python -m ruff check .: passed
python -m compileall -q app scripts tests manage.py: passed
```

## Compatibility

- No database migration.
- No `.env` changes.
- No API-breaking changes; only additive `trainer_control.effective_wait_reason` status payload.
- No Bybit order execution paths added.
- No ML/risk/quality/promotion gate weakening.

Restart API/UI, worker and trainer after update.
