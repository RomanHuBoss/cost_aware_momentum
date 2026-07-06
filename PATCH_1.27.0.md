# Patch 1.27.0 — critical production-drift publication interlock

## Problem

Production drift monitoring was diagnostic only. A `CRITICAL` report changed the worker heartbeat, but the hourly loop ran inference before drift and no signal, plan or acceptance path consulted the persisted report. The same active artifact could therefore continue publishing recommendations after its production behavior crossed a critical threshold. A previously actionable plan also remained acceptable.

## Solution

- Add `production-drift-critical-quarantine-v1`, bound to the exact active model version and reconstructed from successful persisted drift `JobRun` records after restart.
- Latch any `CRITICAL` report for that immutable version; do not clear it on a later `BLOCKED`, monitor disable, restart or same-version reactivation.
- Run mature-outcome resolution and drift before hourly inference.
- Short-circuit signal publication before market/profile queries and record `critical_production_drift` attrition per symbol.
- Force new and recalculated execution plans to `NO_TRADE` and persist the guard evidence in the sizing snapshot.
- Recheck the guard at acceptance so a pre-quarantine actionable plan is superseded and returns `PLAN_RECALCULATION_REQUIRED`.
- Require runtime/signal version to match the current active registry, blocking stale-version publication/acceptance.
- Release only by activating a different governed model version; disabling new monitor jobs does not clear persisted critical evidence.

`BLOCKED` caused by insufficient warm-up observations is intentionally not latched. The monitor requires prospective prediction snapshots from published signals; blocking before the minimum sample exists would permanently prevent the evidence required to leave `BLOCKED`.

## Compatibility

- Database migration: none; Alembic head remains `0014_ui_exposure_ledger`.
- Public HTTP schema and `.env`: unchanged.
- Model artifacts, feature/label schemas and recommendation thresholds: unchanged.
- Advisory-only/read-only Bybit boundary: unchanged.
- Operational change: an active model version that already has a successful persisted `CRITICAL` report for that exact immutable version is quarantined immediately after process restart, upgrade or same-version reactivation. Recovery requires activation of another reviewed version.

## Verification

- Baseline: `627 passed, 4 skipped, 62 warnings`.
- Red evidence: the publication guard contract was absent; four interlock tests failed at collection before implementation.
- Acceptance red: endpoint returned HTTP 200 instead of required 409 until drift conflict precedence was fixed.
- Targeted green: `53 passed` across the interlock and execution/acceptance safety tests.
- Post-change suite: `636 passed, 4 skipped, 62 warnings`.
- `pip check`, `compileall`, `ruff`, frontend `node --check`, version consistency and single Alembic head pass in the isolated environment.
- PostgreSQL integration was not run because no isolated test database URL or server is configured.

## Remaining limitations

This is a safety interlock, not an automatic model-selection or profitability mechanism. It does not implement multivariate drift tests, adaptive control limits, symbol-level quarantine or automatic rollback. It does not explain sparse recommendations or justify relaxing quality, economic or risk gates. Those questions require prospective attrition and mature outcome evidence.
