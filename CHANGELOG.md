# Changelog

## 1.8.21 — 2026-07-01

### Fixed

- Instrument synchronization now filters Bybit `linear` responses to `LinearPerpetual` before validating funding metadata.
- Delivery-settled `LinearFutures` with `fundingInterval=0` no longer abort the entire worker synchronization loop.
- Strict positive funding-interval validation remains unchanged for in-scope perpetual contracts.

### Validation

- Added a deterministic red-to-green regression containing one dated USDT future and one USDT perpetual.
- No database migration, environment variable or public API schema change.

## 1.8.20 — 2026-06-30

### Fixed

- Acceptance no longer converts an incomplete current funding snapshot into a zero-cost scenario.
- Read-only account reconciliation is repeated inside the acceptance transaction after the account-scoped risk lock.
- Current 24-hour turnover is revalidated before acceptance and limits plan notional through the existing `0.0001` policy fraction.
- Missing, zero, negative or non-finite turnover now blocks plan construction instead of silently disabling the liquidity cap.
- Acceptance audit context now records the current liquidity-notional cap.

### Validation

- Added ten deterministic unit/regression cases covering funding completeness, reconciliation failure, liquidity deterioration and Decimal boundaries.
- No database migration, environment variable or public API schema change.

Historical release details before 1.8.20 remain documented in `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md` and prior `docs/ITERATION_REPORT_*.md` files.
