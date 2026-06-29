# Changelog

## 1.8.10 — 2026-06-29

### Fixed

- Corrected trader-perspective funding signs for LONG/SHORT across Decimal risk math, policy evaluation and research backtest.
- Added fail-closed validation for quantitative settings, direct cost scenarios, funding horizons, directional metadata, labels, class distributions and incumbent metrics.
- Revalidated adverse executable entry prices by creating a newly sized plan instead of accepting stale plan economics.
- Rejected future ticker snapshots and future-dated instrument specifications.
- Persisted actual manual-entry stress loss and remaining risk; partial closes now release risk proportionally.
- Made reconciliation aggregate multiple manual trades and detect journal-only positions.
- Enforced exact model artifact feature schema/horizon/calibration metadata and complete finite inference features.
- Aligned cohort-weighted profit factor with equity/drawdown and included idle time in concurrency statistics.
- Valued PlanOutcome from immutable plan entry/planning time.
- Rebuilt the release checksum manifest, which previously referenced four absent files.

### Database

- Added Alembic revision `0006_manual_trade_remaining_risk`.

### Tests

- Added `tests/unit/test_quant_econometric_audit_2026_06_29.py` and expanded related regression suites.

## 1.8.9 — 2026-06-29

- Enforced complete LONG/SHORT directional cohorts in dataset, temporal split, holdout policy and backtest.

## 1.8.8 — 2026-06-29

- Hardened contiguous feature/label construction, probability simplex validation and exit-time policy accounting.

## 1.8.7 — 2026-06-29

- Hardened executable-price acceptance, account snapshot freshness, serialized portfolio-risk acceptance and liquidation blocking.
