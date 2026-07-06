# Technical, trading-logic and econometric audit — release 1.35.4

Date: **2026-07-06**  
Input: `cost_aware_momentum-1.35.3-trainer-recovery-deadlock(1).zip`

## Executive result

The unspecified claims of “15 critical + 4 medium + 8 critical” cannot be independently verified because they contain no module names, reproductions or evidence. This audit does not manufacture a matching count. It confirmed and corrected **three high-severity defects**, **two medium robustness/integrity defects**, and one substantial static-typing debt category.

The most plausible code-level causes of artificial recommendation scarcity were future-dated orderbook and account snapshots masking valid prior rows. The reported HTTP 409 was independently reproduced from the endpoint design: one stale event invalidated the entire exposure batch and the browser regenerated event ids on retry.

## Confirmed and corrected

| Severity | Module | Defect | Effect | Correction |
|---|---|---|---|---|
| High | `app/api/v1/recommendations.py`, `web/js/app.js` | Exposure batch was all-or-nothing and retry regenerated evidence | Repeated 409, rollback of valid events, biased exposure denominator | Per-item terminal statuses; retry only transport/429/5xx; preserve original ids |
| High | `app/services/execution.py`, `app/services/market_snapshots.py` | Absolute-latest orderbook lookup | False stale/future orderbook, `NO_TRADE`, recalculation, sparse actionable plans | Latest-prior query on source and receipt timestamps |
| High | execution/reconciliation/portfolio | Absolute-latest account-equity lookup | False zero capital/unverified profile and global plan suppression | Shared latest-prior account snapshot query |
| Medium | UI exposure/selection report | Exposure hash was not a complete reusable cross-ledger proof | Inconsistent plan/signal/profile/version evidence could evade one layer | Shared opportunity-link and chronology validator |
| Medium | acceptance + process QA | Implicit non-null acceptance evidence; one-second startup-sensitive test | Possible non-fail-closed exception after refactor; flaky release proof | Explicit fail-closed guard; robust timeout regression |

## Mathematics and trading logic reviewed

The following invariants were inspected and retained:

- direction-aware LONG ask / SHORT bid entry semantics;
- complete-fill bounded-depth VWAP and partial/no-fill blocking;
- round-trip fee, residual slippage and directional funding signs;
- TP/SL/TIMEOUT probability simplex and current-entry conditional TIMEOUT repricing;
- stress-loss sizing, total open-risk cap, leverage and margin reserve;
- observed-opportunity policy path with genuine no-trade hours represented as zero;
- purged expanding walk-forward, final holdout, cost-stress, PBO/DSR and dependence-aware gates;
- fail-closed model activation and active-artifact/version binding.

No verified arithmetic defect in these reviewed functions justified changing thresholds or making signals easier to publish.

## Why trained models may still fail gates

A process status of `SUCCESS` means training completed, not that the candidate passed economic validation. Current gates can legitimately reject candidates for insufficient holdout span, low policy trade density, insufficient independent cohorts, unstable walk-forward performance, non-positive cost-stress compounding, weak lower confidence bound, high PBO or insufficient DSR probability.

The archive lacks the candidate metric payload and database rows needed to decide which of those reasons applies to the user's run. Lowering the gates without that evidence would increase false discoveries and likely worsen the reported losses.

## Static analysis

`ruff` passes. `mypy app scripts` still reports **306 errors**, of which at least 22 are missing third-party stubs; many others arise from heterogeneous JSON/Pandas structures. They are not equivalent to 306 runtime defects, but the type baseline is not production-clean and should be reduced in a dedicated release, prioritizing `app/ml/training.py`, `app/ml/drift.py`, trainer lifecycle and market-data boundaries.

## Verification

- `ruff check .`: passed;
- `python -m compileall -q app scripts tests manage.py`: passed;
- `pytest -q`: 725 passed, 7 skipped;
- `node --check web/js/app.js`: passed;
- release manifest verification: passed after rebuilding;
- PostgreSQL integration: not run, no isolated test database supplied.

## Residual risks

Forward profitability is not established. Historical exact bid/ask and orderbook depth before prospective collection, queue position, operator latency, sub-hour barrier ordering, historical risk tiers/MMR, liquidation fees, cross/portfolio margin and ADL remain incomplete or proxy-modeled. Actual loss attribution requires the production database, immutable candidate metrics, decisions, fills and counterfactual outcomes.
