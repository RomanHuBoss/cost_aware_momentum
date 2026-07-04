# Changelog

## 1.9.3 — 2026-07-04

### Fixed

- Enforced `MAX_TOTAL_OPEN_RISK_RATE` and `MAX_LEVERAGE` as process-wide ceilings for all capital profiles.
- Unsafe legacy profiles now fail closed during plan creation, activation and acceptance instead of producing actionable sizing.
- Omitted profile-policy fields resolve from runtime settings; frontend no longer injects hard-coded total-risk and margin defaults.
- Portfolio diagnostics expose invalid profile policy while calculating the effective limit from the global cap.

### Verification

- Added red → green regressions proving that a 20% profile could previously create and accept an actionable plan under the default 2% global cap.
- Added policy/API/default/patch/frontend tests; no migration or new environment variable.

## 1.9.2 — 2026-07-04

### Fixed

- Hourly signal publication now requires the latest confirmed candle to close exactly at `signal.event_time`.
- A previous-hour candle can no longer publish a current-hour signal and occupy the natural key before the correct candle arrives.
- Added explicit fail-closed diagnostics for a missing, stale or impossible future decision candle.

### Verification

- Added an independent regression test reproducing the previous-hour substitution.
- Preserved all ML, risk, cost, execution-plan and auto-activation thresholds.
- No database migration, environment-variable or public API change.

## Historical note

The supplied 1.9.1 archive did not contain `CHANGELOG.md` or prior `PATCH_*.md` files even though its internal iteration report referenced them. Earlier history has not been reconstructed from unverifiable material; dated iteration reports remain the source for previous changes.
