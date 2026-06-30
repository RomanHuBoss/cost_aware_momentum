# Patch 1.8.12 — open-gap barrier integrity

## Problem

The barrier path used only hourly high/low/close. It therefore lost the only ordered point inside an OHLC candle: the open. A favorable opening gap could be mislabeled as a conservative stop if the same candle later touched both barriers; an adverse opening gap was capped at the stop; and its exit time was shifted to candle close. Downstream holdout promotion also replaced every realized SL with the planned stress loss, while backtest and plan-outcome valuation could subtract the complete stop-gap reserve after the realized exit price already contained the gap.

## Solution

- Barrier labels and counterfactual outcomes now require coherent full OHLC and resolve `open` before unordered intrabar extrema.
- Favorable TP opening gaps are conservatively capped at the target; adverse SL opening gaps use the observed open price.
- Opening-gap outcomes use `open_time`; research metadata stores `exit_at_open` and propagates the exact modeled exit time.
- Generated artifacts record `label_path_schema_version=ohlc-open-first-stop-gap-v1`.
- Holdout promotion uses the realized gross return and actual exit-notional fee for TP, SL and TIMEOUT.
- For SL results, only the configured stop-gap reserve not already embedded in the observed gap is retained in holdout metrics, research backtest and PlanOutcome valuation.
- Policy metrics now use `exit-time-realized-gap-horizon-sleeves-v3`; counterfactual outcomes use `primary-barrier-intrabar-open-gap-v4`.

## Compatibility and operations

- No Alembic migration and no new `.env` variables.
- Alembic head remains `0006_manual_trade_remaining_risk`.
- Existing runtime artifacts remain feature/class compatible, but candidate/incumbent policy metrics produced under schema v2 are deliberately ineligible for automatic comparison with v3.
- Retrain candidate artifacts and recompute holdout/backtest metrics before comparison with 1.8.11 results.
- Restart API, inference worker and trainer after replacing the release.

## Verification

- New focused regression module: `tests/unit/test_barrier_open_gap_integrity.py`.
- Red on unmodified 1.8.11: `8 failed` for the intended reasons.
- Green after correction: `8 passed`.
- Full suite after correction: `272 passed, 4 skipped, 19 warnings`.

## Limitations

Hourly bars still cannot order TP and SL touches after the open. A complete configured lower-timeframe path is used when available; otherwise the established conservative same-bar SL rule remains. Stop-gap reserve remains a conservative model input, not evidence of actual exchange execution.
