# Patch 1.7.8 — atomic model candidate promotion

## Problem

New candidate promotion was split across two independent PostgreSQL transactions:

1. `register_model_candidate()` inserted the inactive registry row with `activation_requested=true` and committed candidate audit/outbox events.
2. `activate_registered_model()` later validated and switched the active row in a second transaction.

A process crash, database error, audit-chain failure or outbox failure between those calls could leave a gate-passed candidate durably registered but inactive. The trainer result was then incomplete and automatic recovery depended on a later operator or scheduler path. Existing tests mocked registration and activation independently and did not verify rollback across the full promotion boundary.

## Change

- Added `register_and_activate_model_candidate()` in `app.ml.lifecycle`.
- Artifact SHA256/version/schema/classes/horizon validation runs before database mutation.
- The current active registry row is selected `FOR UPDATE` and must match the expected incumbent version.
- Candidate insertion, candidate audit/outbox, incumbent deactivation, target activation and activation audit/outbox occur inside one `session.begin()` transaction.
- Background trainer, `python manage.py train --activate` and gate-passed orphan recovery use the atomic path.
- Failed-gate and manual-review candidates continue to use standalone inactive registration.
- Activation of an already registered historical candidate remains an explicit reviewed operation and is outside this new-candidate transaction.

## Compatibility

- Patch release; no REST, JSON, `.env` or PostgreSQL schema changes.
- Alembic head remains `0005_plan_outcome_invalid_input`.
- Existing inactive candidates and manual `model-registry activate` behavior remain supported.
- Advisory-only, PostgreSQL-only and separate-process boundaries are unchanged.

## Verification

- RED: `python -m pytest -q tests/unit/test_atomic_model_promotion.py` failed during collection because `register_and_activate_model_candidate` did not exist.
- GREEN targeted: atomic promotion and related lifecycle/recovery tests pass.
- Full post-check results are recorded in `docs/QA_REPORT.md` and `docs/ITERATION_REPORT_2026-06-28-atomic-model-promotion.md`.
