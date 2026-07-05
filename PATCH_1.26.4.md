# Patch 1.26.4 — observed-opportunity policy return path

## Problem

`evaluate_policy_model` formed economic policy cohorts only from executed research trades. An observed final-holdout hour in which all directions failed the policy or overlap filter was omitted rather than recorded as a zero strategy return. Consequently, mean R and bootstrap evidence were conditional on the policy's own selected sample. Sparse policies could look materially better than their actual hourly decision process, while horizon-phase completeness could change merely because trades happened to occur in particular phases.

## Solution

- Build the policy denominator from every observed `selected.decision_time`.
- Aggregate trade returns by decision hour, then reindex only onto that observed opportunity index with zero for no-trade hours.
- Use the same unconditional path for mean realized/expected R, all horizon phases and moving-block bootstrap LCB.
- Expose `policy_trade_cohorts`, `policy_no_trade_cohorts`, trade-conditional diagnostics and opportunity win rate separately.
- Validate candidate and incumbent opportunity counts fail-closed.
- Raise policy metric schema to v17 and uncertainty schema to v3 so legacy conditional evidence cannot be silently reused.

## Compatibility and operator action

- Database migration: none.
- `.env` additions or threshold changes: none.
- Public HTTP API: unchanged.
- Already active artifacts remain active and readable.
- Inactive candidates evaluated before 1.26.4 have incompatible policy evidence. Retrain the candidate, then rerun the preregistered experiment family for normal activation.
- Do not lower policy gates to recover recommendation frequency. First inspect the candidate/live attrition report and the new trade/no-trade cohort counts.

## Verification

- Baseline: 613 passed, 4 skipped, 61 warnings.
- Red evidence: 1 failed in `test_policy_opportunity_path_2026_07_05.py` on the original code.
- Green targeted evidence: 34 passed; isolated regression 1 passed in 2.97 s.
- Full post-change suite: 615 passed, 4 skipped, 61 warnings.
- Ruff, compileall, pip check and JavaScript syntax: passed.
- PostgreSQL integration: not run; no separate PostgreSQL test URL was configured.

## Limitations

This patch corrects the inference denominator. It does not promise profitability, reconstruct historical order books or funding forecasts, change signal thresholds, increase recommendation frequency, or model exchange liquidation mechanics exactly.
