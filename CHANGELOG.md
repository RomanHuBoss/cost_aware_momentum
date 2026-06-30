# Changelog

## 1.8.11 — 2026-06-29

### Fixed

- Normalized holdout policy total R and drawdown by the configured holding-horizon capital sleeves and bound promotion metrics to an explicit schema/horizon.
- Rejected TP/TIMEOUT returns and `label_end_time` values inconsistent with the configured barrier horizon before direction ranking.
- Reprojected cumulative funding from execution-plan creation time instead of reusing the signal-time scenario; missing interval metadata now blocks a known non-zero settlement.
- Rejected fractional/boolean/non-positive leverage instead of silently truncating it.
- Required exact bar duration and coherent OHLC (`low <= close <= high`) in outcome evaluation.
- Rejected naive or future-dated manual entry/close fills before journal mutation.

### Compatibility

- No migration or environment-variable change.
- Policy metrics use `exit-time-horizon-sleeves-v2`; legacy metric payloads are not eligible for automatic model promotion.
- New counterfactual evaluations use `primary-barrier-intrabar-v3`.

### Tests

- Added `tests/unit/test_quant_integrity_2026_06_29.py` and a legacy-policy-schema gate regression.

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
