# Patch 1.9.3 — global capital risk-policy enforcement

## Problem

Runtime configuration declared `MAX_TOTAL_OPEN_RISK_RATE=0.02` and `MAX_LEVERAGE=5`, but capital-profile inputs allowed `max_total_risk_rate` up to 0.20 and the execution/acceptance paths multiplied capital by the persisted profile value directly. The global limits were validated at startup but were not enforced against profile creation, modification, activation or legacy rows already present in PostgreSQL.

A profile with a 20% total-risk limit therefore produced an `ACTIONABLE` plan and passed acceptance under default settings. This is a confirmed financial-safety defect; it does not prove that any specific historical loss was caused by it.

## Resolution

- Added one centralized capital-profile policy contract:
  - `0 < risk_rate <= max_total_risk_rate <= MAX_TOTAL_OPEN_RISK_RATE`;
  - `1 <= default_leverage <= max_leverage <= MAX_LEVERAGE`;
  - finite `margin_reserve_rate` in `[0, 1)`.
- Runtime settings now supply omitted create-profile defaults.
- Create, patch and activation reject unsafe policy values with HTTP 422 before mutation/recalculation.
- Plan construction revalidates persisted profiles; unsafe legacy rows produce `BLOCKED_INVALID_INPUT` and use safe runtime defaults only for a non-actionable diagnostic snapshot.
- Acceptance revalidates the same policy and supersedes the stale plan instead of accepting it.
- Portfolio diagnostics use the enforced global cap and expose `INVALID_CAPITAL_PROFILE_POLICY` for unsafe legacy rows.
- Frontend no longer injects hard-coded total-risk/margin defaults and displays each profile's total-risk limit.

## Compatibility

- Version: 1.9.3 patch release.
- Database migration: none; Alembic head remains `0009_candle_receipt_availability`.
- New `.env` variables: none.
- API: create-profile risk/leverage fields are optional and omitted values resolve from runtime settings; explicit unsafe values are rejected. Existing valid payloads and responses remain compatible.
- Model artifacts/retraining: unchanged.

## Operator action

Review existing capital profiles before activation. Correct any profile that exceeds the configured global risk/leverage ceilings. Do not bypass the block by editing PostgreSQL or increasing limits solely to make a recommendation actionable.

## Verification

See `docs/ITERATION_REPORT_2026-07-04_global-risk-policy.md` and `docs/QA_REPORT.md` for baseline, red/green and post-check evidence.
