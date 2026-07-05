# Patch 1.26.6 — hourly mark-to-market experiment return path

## Problem

`_simulate_capital_sleeves_evidence` recognized every trade's complete P&L only at `exit_time`. A trade that fell materially during the holding interval and recovered before exit therefore showed no interim capital loss. This understated drawdown and changed the return distribution used by Sharpe, HAC effective sample size, Deflated Sharpe, CSCV/PBO and moving-block confidence intervals.

Minimal reproduction: a two-hour trade with cumulative returns `0%, -20%, +1%` and a two-hour sleeve allocation of 50% previously emitted portfolio period returns `0%, 0%, +0.5%` and `max_drawdown=0`. The correct capital path is `0%, -10%, +11.666…%`, ending at the same +0.5% portfolio result but with a -10% drawdown.

## Solution

- Label construction now preserves a complete cumulative hourly mark-close path from decision time through the effective barrier/timeout/liquidation exit.
- Each path carries directional gross return and trader-signed historical funding and is validated for schema, chronology, hourly coverage and terminal reconciliation.
- Backtest converts that evidence to cumulative net returns: entry fee and conservative slippage at decision time, funding along the observed settlement path, and terminal exit fee plus modeled exit outcome at effective exit.
- Capital-sleeve accounting applies path increments at every covered hour and still reconciles exactly to terminal sleeve capital.
- Experiment evidence is fail-closed when the path is missing or invalid.
- Return-path schema is now `observed-opportunity-covered-hourly-mark-to-market-capital-return-path-v3`; exit-realized v2 evidence cannot authorize normal promotion.

## Compatibility

- Database migration: none.
- Public API: unchanged.
- `.env`: unchanged.
- Model feature, label and runtime artifact schemas: unchanged.
- Risk, EV/RR and quality thresholds: unchanged.
- Active artifacts remain runnable.
- Existing experiment families with successful v2 evidence require governed backtest reruns before normal promotion.

## Verification

- Baseline: `618 passed, 4 skipped`.
- Red evidence: `test_capital_sleeve_evidence_marks_intrahorizon_drawdown_before_profitable_exit` failed with exit-only returns `[0.0, 0.0, 0.005]` instead of `[0.0, -0.10, 0.116666…]`.
- Green evidence: the same test passes after the patch.
- Post-change suite: `622 passed, 4 skipped, 62 warnings`.
- `pip check`, `compileall`, `ruff`, and frontend `node --check` pass in the isolated environment.
- PostgreSQL integration was not run because no isolated PostgreSQL test URL is configured.

## Remaining limitations

Hourly close MTM cannot reconstruct sub-hour path order, queue position, exact historical bid/ask/depth, operator latency, exchange risk-tier changes, cross/portfolio margin, ADL or exchange-accurate liquidation fills. The patch improves research evidence; it does not establish profitability or justify weakening recommendation gates.
