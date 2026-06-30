# Patch 1.8.14 — quant policy integrity

## Problem

The audit reproduced five independent correctness failures: favorable projected funding could improve a recommendation without proof that the position survived to settlement; cross-sectional symbols were treated as independent promotion evidence and distorted mean policy returns; accepted/live/closed plans could be recalculated into parallel versions; plan-version allocation raced under concurrent transactions; and an invalid default horizon could pass configuration validation.

## Resolution

- Pre-trade and static research funding recognize only adverse projected cash flow. Realized outcome accounting still applies signed funding after crossed settlements are known.
- Policy metric schema advanced to `exit-time-open-gap-propagated-cohort-weighted-v5`; mean R/EV is cohort-weighted, profit factor follows net exit events, and `policy_cohorts` is a required auto-activation metric.
- `ACCEPTED`, `ENTERED`, `PARTIAL`, and `CLOSED` plans are immutable to recalculation.
- `(signal_id, profile_id)` version allocation uses `pg_advisory_xact_lock` before `max(version)+1`.
- `DEFAULT_HORIZON_HOURS` must be positive and declared in `HORIZONS_HOURS`.

## Compatibility

No Alembic migration and no new `.env` variable. Alembic head remains `0006_manual_trade_remaining_risk`. Candidate/incumbent v4 policy metrics must be recomputed. Existing live/terminal plans are preserved and no longer duplicated by recalculation.

## Verification

Focused red baseline: `6 failed`. Corrected focused suite: `6 passed`. Full post-change unit suite: `282 passed, 4 skipped`. Compile, Ruff, Node syntax, Alembic head and clean release-integrity checks pass. PostgreSQL integration and native doctor remain unverified because no disposable test database/native `.venv` was available.

## Limitation

The project remains advisory-only. Static backtests still do not model exact historical funding timestamps; therefore they conservatively reject favorable credits rather than invent settlement exposure.