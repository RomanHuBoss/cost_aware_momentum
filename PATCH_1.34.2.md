# Patch 1.34.2 — Timezone-stable universe snapshot hashes

## Problem

Trainer control could fail before deciding whether training was due:

```text
ValueError: Universe eligibility snapshot record hash mismatch
```

The failure path was:

`trainer.process_control_request` → `due_reason` → `current_training_profile` →
`load_training_data_profile` → `load_training_market_data` →
`load_point_in_time_universe_snapshots` →
`validate_universe_eligibility_snapshot_record`.

The immutable snapshot hash included `observed_at` and `recorded_at` using the textual
UTC offset returned by `datetime.isoformat()`. PostgreSQL `TIMESTAMPTZ` stores an instant,
but may return that instant rendered in the connection/session timezone. A row written as
`2026-07-06T12:00:00+00:00` and read as `2026-07-06T15:00:00+03:00` therefore produced
different JSON bytes despite representing the same instant.

Existing tests persisted and validated the same in-memory ORM object, so they did not
exercise the PostgreSQL timezone round trip.

## Correction

- Canonicalize top-level universe snapshot `observed_at` and `recorded_at` to UTC before
  both persistence hashing and replay revalidation.
- Keep policy hash, decision coverage, selected-symbol consistency and record hash checks
  fail-closed.
- Add exact `snapshot id`, `mode` and `recorded_at` to replay validation failures so a truly
  corrupt row can be identified without disabling validation.
- Add regression tests for equivalent instants represented with different UTC offsets and
  for exact invalid-row diagnostics.

## Compatibility

- Database migration: none; Alembic head remains `0016_universe_replay_asof`.
- `.env`: no changes.
- API/UI schema: no changes.
- Model artifact/feature/label schema: no changes.
- Risk, quality, promotion and activation gates: unchanged.
- Existing production snapshots written by the worker use UTC timestamps and retain the
  same record hash after canonicalization; rows are not rewritten.

## Operator action

1. Replace the project with release 1.34.2.
2. Restart the trainer process. Restarting API/worker at the same maintenance point is
   recommended so every process reports the same release version.
3. Repeat the trainer control action.
4. If validation still fails, use the new snapshot identity in the error to inspect that
   exact immutable row; do not delete or update the row in place.

## Verification

- Baseline: `692 passed, 7 skipped, 62 warnings`.
- Red: timezone-invariance regression failed with `Universe eligibility snapshot record hash mismatch`.
- Green targeted/related suite: `48 passed` before the final diagnostic test was added;
  final two new regressions pass together.
- Full post-change suite: `694 passed, 7 skipped, 62 warnings`.
- Ruff, compileall, pip check, Node syntax and Alembic single-head checks pass.
- PostgreSQL integration execution was not available in this environment; seven integration
  tests were collected and skipped.
