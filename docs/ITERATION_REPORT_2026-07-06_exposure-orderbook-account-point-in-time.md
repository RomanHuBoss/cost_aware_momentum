# Iteration report: exposure conflict and point-in-time execution state

Release: **1.35.4**  
Date: **2026-07-06**

## Confirmed defects

### 1. Batch-wide exposure conflict loop — high operational/econometric severity

`POST /api/v1/recommendations/exposures` aborted the whole transaction with HTTP 409 when any item referred to an unknown plan, stale plan version, damaged ledger or conflicting event id. The browser then removed every plan from its local exposed set, restarted dwell measurement and generated new event ids. One obsolete card could therefore roll back valid rows, create repeated 409 requests and lower or distort prospective exposure coverage.

Correction:

- each event is classified independently;
- valid rows commit even when another item is stale or invalid;
- permanent outcomes are returned as terminal item statuses in HTTP 200;
- transport/429/5xx retry preserves the original `client_event_id` and `page_instance_id`;
- browser no longer repeats dwell measurement after a permanent semantic conflict.

### 2. Absolute-latest orderbook selection — high trading-availability severity

Plan construction and acceptance selected the maximum `source_time` before applying freshness checks. A future-dated row therefore masked an older orderbook that was already received and still fresh. The result was a false missing/stale orderbook path, `NO_TRADE`, recalculation or rejection.

Correction: shared latest-prior orderbook selection now requires both `source_time <= cutoff` and `received_at <= cutoff`, then orders deterministically by source time, receipt time and id.

### 3. Absolute-latest account snapshot selection — high risk/availability severity

Read-only effective capital and reconciliation used the absolute newest account snapshot. A future timestamp masked an older valid snapshot and caused `effective_capital=0`, unverified capital or inconsistent portfolio display. This could suppress every plan for the profile even while a usable snapshot existed.

Correction: effective-capital, reconciliation and portfolio paths now use the same latest-prior availability contract.

### 4. Exposure evidence was only self-consistent — medium econometric severity

The exposure row hash and intrinsic bounds were verified, while opportunity linkage checks were duplicated inside one report. Duplicate handling in the API did not require a complete cross-ledger match. The evidence is now validated against the originating immutable opportunity across plan, signal, profile, plan version and chronology through one shared function.

### 5. Acceptance evidence assumption and QA timeout — medium robustness severity

The successful acceptance path dereferenced `acceptance_validation` based on implicit control-flow assumptions. A future refactor could produce an attribute error rather than a fail-closed recalculation. An explicit missing-evidence conflict and post-guard invariant were added. The one-second descendant-process timeout regression was also startup-sensitive in the audit environment; it now retains the same termination proof with a three-second timeout.

## Deliberately unchanged

No model quality, walk-forward stability, trade-density, holdout-span, PBO/DSR, cost-stress, activation, EV/RR, leverage or risk limit was relaxed. A training process completing successfully still does not imply that its candidate is economically acceptable.

## Limits of this audit

The archive contains no operator PostgreSQL database, candidate artifacts, candidate metric payloads, production drift reports or actual trade journal. Therefore this release cannot determine why a particular trained model failed its gates, reconstruct the user's realized losses or establish forward profitability. PostgreSQL integration tests remain skipped without an isolated `TEST_DATABASE_URL`.
