# Patch 1.21.0 — prospective recommendation UI exposure ledger

## Problem

Release 1.20.0 recorded every execution-plan version as an ex-ante operator-selection opportunity, but the selection report implicitly treated plan creation as operator exposure. A plan could have been generated while the browser tab was hidden, the card was below the viewport, the operator was logged out, or the UI was not open at all. Classifying such plans as `NO_DECISION` mixed “not selected” with “not seen” and biased the denominator used by propensity/IPSW diagnostics.

## Solution

Release 1.21.0 adds prospective first-party UI exposure evidence:

- a recommendation tile must remain at least 50% visible for at least 1000 ms while the document is visible;
- the browser submits authenticated, CSRF-protected batch events;
- the server verifies plan ID/version, immutable opportunity integrity, event age, clock skew, viewport ratio and dwell;
- the first valid exposure is stored idempotently in `advisory.selection_exposure_ledger`;
- a canonical SHA-256 covers the immutable evidence, and PostgreSQL rejects UPDATE/DELETE;
- selection analysis uses only verified exposed opportunities and orders them by `exposed_at`;
- coverage, legacy exclusions and decisions without exposure are reported explicitly;
- low exposure coverage or corrupted evidence blocks the corrected IPSW estimate.

The endpoint writes evidence only. It does not change plan status, recommendation direction, risk, fills, model activation or any Bybit state.

## Rollout semantics

Exposure evidence is prospective from instrumented release 1.21.0. Unexposed pre-1.21 opportunities are excluded from the instrumentation denominator rather than labelled as missed impressions. A legacy plan can enter the cohort if it is actually displayed by the new UI and receives valid exposure evidence.

## Compatibility

- Database migration required: `0014_ui_exposure_ledger`.
- New setting: `SELECTION_MIN_EXPOSURE_COVERAGE=0.80`.
- No market-model retraining is required.
- Market-model artifact schemas are unchanged.
- Operator report schema changes to `operator-selection-ipsw-exposure-clustered-report-v3`.
- Clients using API/CLI channels do not create UI exposure and therefore do not enter the exposure-conditioned denominator unless another explicitly instrumented surface is implemented later.

## Validation

- Baseline: 568 passed, 4 skipped.
- Post-change: 582 passed, 4 skipped.
- New UI-exposure regression module: 14 passed.
- Ruff, compileall, frontend syntax and Alembic-head checks passed.
- PostgreSQL integration migration was not executed because no isolated `TEST_DATABASE_URL` was available.

## Limitations

- Visible dwell is not eye tracking and does not prove attention, comprehension or intent.
- Browser delivery can be delayed until a retry; server-side age/skew limits reject unsafe events.
- Exposure is recorded only for the first-party recommendation tile, not notifications, API consumers or copied links.
- Hidden operator state remains unobserved, and propensity bootstrap does not refit the model inside every replicate.
- Corrected operator-selection estimates remain descriptive and do not prove causal operator skill or profitability.
