# Iteration report — policy correlation-cluster jackknife robustness

## 1. Input

- Archive: `cost_aware_momentum-1.43.0-policy-symbol-jackknife-robustness.zip`
- SHA-256: `4e9d19cf974a19480ea084d4f7ddbae945bc002bed06eec026d8b7c3ca160373`
- Source version: 1.43.0
- Target version: 1.44.0

## 2. Goal and acceptance criteria

After this iteration, normal activation must reject a candidate whose positive final-holdout result disappears after removal of any whole cluster of strongly dependent traded symbols.

Acceptance criteria:

1. Clusters are derived deterministically from exact actionable/post-overlap trades.
2. Correlation configuration is immutable and included in evidence.
3. Counterfactual recomputation preserves the observed opportunity clock and no-trade zeros.
4. Quality gate fails if fewer than two clusters remain or any cluster removal destroys the minimum mean-R requirement.
5. Symbol and cluster evidence describe the exact same symbol set.
6. Runtime rejects missing or malformed evidence.
7. Full existing suite remains green.

## 3. Data flow

`final holdout probabilities → direction selection → EV/RR actionability → overlap filter → realized R by symbol/time → dependence graph → connected components → leave-one-cluster-out opportunity returns → artifact metrics → quality gate → runtime validation`.

## 4. Baseline

- `python -m pip check`: FAILED due unrelated shared-environment `moviepy`/Pillow conflict.
- compileall: PASSED.
- Ruff: PASSED.
- pytest: **782 passed, 8 skipped**.
- Node syntax: PASSED.

## 5. Confirmed defect

**Severity: high.** Single-symbol jackknife does not detect a group of correlated winner proxies. A deterministic cohort with two correlated winners and one loser passed every single-symbol removal, but removal of the winner component left `-0.20 R`. Existing 1.43.0 code had no group-level robustness evidence or gate.

The original new test file on untouched 1.43.0 produced **6 failed, 1 passed**. The passing test was the independent numerical masking demonstration.

## 6. Implementation

Production:

- `app/ml/training.py`: cluster construction, counterfactual recomputation, immutable validator, policy schema v21.
- `app/ml/lifecycle.py`: quality-gate enforcement, cross-evidence symbol-set check and diagnostics.
- `app/ml/runtime.py`: mandatory artifact validation.
- `app/__init__.py`, `pyproject.toml`: version 1.44.0.

Tests:

- Added `tests/unit/test_policy_cluster_jackknife_robustness_2026_07_07.py`.
- Updated shared artifact/quality fixtures to include current cluster evidence.

No migration, API or `.env` change.

## 7. Red → green

- Red on untouched 1.43.0: `6 failed, 1 passed`.
- Green final regression file: `8 passed`.
- The eighth test verifies exact symbol-set agreement and was added after the original red run.

## 8. Post-check

- compileall: PASSED.
- Ruff: PASSED.
- pytest: **790 passed, 8 skipped**.
- Node syntax: PASSED.
- Alembic: one head, `0017_model_artifact_blobs`.

## 9. Not verified

- PostgreSQL integration suite and upgrade against an isolated database.
- Full training and activation on the operator dataset.
- Stability of inferred clusters on forward data.
- Market-regime conditional performance and per-symbol calibration.
- Live profitability.

## 10. Residual risks

- Correlation is estimated from realized final-holdout actionable returns and may be noisy.
- Symbols with fewer than eight simultaneous trades are left disconnected.
- Connected components can merge through transitive links even when endpoint correlation is below threshold; this is conservative by design.
- The check does not model ex-ante sector classification or causal dependence.

## 11. Rollback

Restore the 1.43.0 code and reactivate only an artifact valid under that release. No database rollback is needed. Rollback removes the cluster gate and therefore reopens the documented group-concentration risk.

## 12. Recommended next package

Add preregistered market-regime stratification of the exact actionable final holdout, with minimum observations and worst-regime calibration/economic gates. Do not implement it by weakening current cluster, holdout or trade-count thresholds.
