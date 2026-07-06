# Changelog

## 1.34.2 — 2026-07-06

### Fixed

- Canonicalized universe eligibility snapshot `observed_at` and `recorded_at` to UTC before record hashing and revalidation.
- Prevented PostgreSQL session timezone rendering from producing false immutable-ledger hash mismatches that blocked trainer control and training-data profiling.
- Preserved fail-closed validation for actual snapshot tampering and added exact snapshot identity/timestamp diagnostics.
- Added regression coverage for timezone-invariant hash verification and invalid-row diagnostics.

## 1.34.1 — 2026-07-06

### Fixed

- Eliminated a research-to-production policy mismatch in expected funding semantics: live market-signal direction can no longer be flipped by a funding forecast absent from final-holdout promotion evidence.
- Kept fresh projected funding as a fail-closed execution-plan and acceptance overlay, preserving adverse-funding downside, net-edge and sizing checks.
- Added explicit persisted economics assumptions and regression coverage for the market-signal/execution separation.
- Rebuilt the release boundary and checksum manifest without caches, bytecode, egg-info or stale entries.

## 1.34.0 — 2026-07-06

- Added process-tree containment for automatic-experiment cancellation, timeout and failure cleanup.
