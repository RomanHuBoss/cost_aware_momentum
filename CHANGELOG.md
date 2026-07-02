# Changelog

## 1.8.33 — 2026-07-02

### Fixed

- Prevented the uncalibrated deterministic baseline from producing or preserving actionable execution plans by default; legacy baseline plans now fail closed at acceptance.
- Removed the hidden universal TIMEOUT return assumption from live/promotion call sites by introducing one validated `TIMEOUT_GROSS_RETURN_RATE` setting and persisting it with signal/plan economics.
- Split `AUTO_TRAIN_MIN_POLICY_COHORTS` from raw `AUTO_TRAIN_MIN_POLICY_TRADES`; the previous code unintentionally used the trade threshold for both gates.

### Changed

- Signal snapshots now persist model-runtime provenance and economics assumptions.
- Status diagnostics expose baseline actionability, TIMEOUT assumption and both policy sample thresholds.
- Production rejects `ALLOW_BASELINE_ACTIONABLE=true`.

### Verification

- Added regression coverage for baseline plan blocking, legacy acceptance blocking, explicit TIMEOUT economics, serializer parity and independent cohort gating.
- PostgreSQL integration remains environment-dependent; no schema migration is required.

## 1.8.32 — 2026-07-02

### Fixed

- Removed the accidentally packaged duplicate Alembic 0008 branch, restoring one deployable head: `0008_outcome_path_unavailable`.
- Aligned research backtest and model-promotion policy with live acceptance: only one active position per symbol/account scope is counted until the modeled exit boundary.
- Corrected trade counts, trade rate, return, drawdown, concurrency and promotion evidence so blocked same-symbol overlaps cannot inflate econometric results.
- Restored the missing release provenance files (`CHANGELOG.md`, patch note and `SHA256SUMS`).

### Changed

- Policy metric schema is now `exit-time-open-gap-single-symbol-cohort-v7`.
- Backtest reports `actionable_candidates` and `overlap_blocked_trades`; promotion metrics report the corresponding `policy_*` fields.

### Verification

- Regression tests cover overlap rejection, exact exit-boundary re-entry and the Alembic revision/head contract.
- PostgreSQL integration and real migration execution remain environment-dependent and were not claimed in this release.

## 1.8.31 — 2026-07-02

- Intended to shorten migration 0008 revision ID to fit Alembic's standard 32-character version column. The supplied 1.8.31 archive was internally inconsistent because it still contained both the corrected and obsolete 0008 files and omitted its stated release manifest; 1.8.32 repairs that packaging regression.
