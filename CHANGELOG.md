# Changelog

## 1.8.14 — 2026-06-30

### Fixed

- Removed favorable projected funding credits from pre-trade RR/EV, direction selection and static research backtests when the actual exit time and crossed settlement are unknown; adverse funding remains charged conservatively.
- Rebased policy mean return and expected EV on equal-weight hourly decision cohorts instead of raw symbol count, and calculated promotion profit factor from the net portfolio exit-event path.
- Added `policy_cohorts` to the v5 policy metric contract and required the same minimum number of independent hourly cohorts as raw trades before auto-activation.
- Prevented recalculation from creating a second plan over `ACCEPTED`, `ENTERED`, `PARTIAL` or `CLOSED` state, including bulk profile recalculation and accept-conflict recovery.
- Serialized `(signal_id, profile_id)` plan-version allocation with a PostgreSQL transaction-scoped advisory lock.
- Rejected non-positive `DEFAULT_HORIZON_HOURS` and defaults absent from `HORIZONS_HOURS`.

### Compatibility

- No migration and no new environment variable; Alembic head remains `0006_manual_trade_remaining_risk`.
- Candidate/incumbent policy metrics must be recomputed under `exit-time-open-gap-propagated-cohort-weighted-v5`; v4 metrics are intentionally ineligible for automatic comparison.
- Existing accepted/entered/partial/closed plans remain immutable; operators must complete or reject the relevant lifecycle rather than force a recalculation.

### Tests

- Added six red-to-green regressions covering funding recognition, cohort weighting, independent-evidence gating, immutable-plan recalculation, version allocation locking and horizon configuration.

## 1.8.13 — 2026-06-30

### Fixed

- Preserved `exit_at_open` through the production chronological dataset split instead of silently dropping opening-gap timing before holdout evaluation.
- Rejected training/policy/backtest metadata that omits the required opening-exit flag, preventing a silent fallback that shifted all exits to candle close.
- Bumped the policy metric contract to `exit-time-open-gap-propagated-horizon-sleeves-v4`, so corrected metrics cannot be compared or auto-promoted against affected v3 evidence.

### Compatibility

- No migration or environment-variable change; Alembic head remains `0006_manual_trade_remaining_risk`.
- Manual research `DatasetSplit.test_meta` inputs must include boolean `exit_at_open` for every row.
- Recompute candidate/incumbent holdout and research backtest metrics before comparison; v3 policy metrics are intentionally rejected.

### Tests

- Added four red-to-green regressions for split propagation, missing-field rejection and policy-schema isolation.

## 1.8.12 — 2026-06-30

### Fixed

- Resolved candle opens before unordered intrabar high/low in training labels and counterfactual outcomes.
- Capped favorable opening TP gaps at the modeled target while valuing adverse stop gaps at the observed open price and open timestamp.
- Required coherent full OHLC (`low <= open/close <= high`) for barrier paths.
- Preserved exact opening-gap exit time through policy metadata instead of shifting it to candle close.
- Used realized SL returns in promotion metrics instead of capping every loss at the planned stress barrier.
- Prevented double counting of stop-gap reserve when the realized exit price already contains part or all of the gap loss in holdout policy, research backtest and plan-outcome valuation.

### Compatibility

- No migration or environment-variable change; Alembic head remains `0006_manual_trade_remaining_risk`.
- Policy metrics use `exit-time-realized-gap-horizon-sleeves-v3`; v2 payloads must be recomputed before automatic promotion comparisons.
- New artifacts record `label_path_schema_version=ohlc-open-first-stop-gap-v1`.
- New counterfactual evaluations use `primary-barrier-intrabar-open-gap-v4`.

### Tests

- Added eight red-to-green barrier/open-gap, timestamp, promotion, backtest and plan-valuation regressions in `tests/unit/test_barrier_open_gap_integrity.py`.

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
