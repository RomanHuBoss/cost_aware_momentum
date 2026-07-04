# Changelog

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
