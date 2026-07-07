# Iteration report — Policy market-regime robustness

## 1. Input

- Input archive: `cost_aware_momentum-1.44.0-policy-cluster-jackknife-robustness.zip`
- Input SHA-256: `796a46708b8687b04573ae94b36f434e42d5b868df6efb018b3803b60b742465`
- Source version: 1.44.0
- Target version: 1.45.0
- Alembic head: `0017_model_artifact_blobs` before and after

## 2. Goal and acceptance criteria

After this iteration, normal activation and runtime loading must reject a candidate whose aggregate actionable final-holdout result masks an unsupported, poorly calibrated or non-positive market regime.

Acceptance criteria:

1. Regimes use only decision-time features and a development-only volatility threshold.
2. Every observed opportunity belongs to exactly one deterministic regime.
3. Per-regime opportunities, trades, no-trade cohorts, calibration rows and fractions reconcile exactly with aggregate policy evidence.
4. Every traded regime has at least five trades.
5. Every traded regime passes the existing mean-R, log-loss and multiclass-Brier limits.
6. Missing, malformed or legacy evidence fails closed at quality gate and runtime.
7. Full existing unit/static suite remains green.

## 3. Sources and data flow

Read: README, CHANGELOG, PATCH_1.44.0, QA report, specification compliance, traceability, training/lifecycle/runtime code and symbol/cluster/actionable calibration regressions.

Changed flow:

`development x_train → market-median ATR 75th-percentile cutoff → final-holdout selected decision-time features → deterministic regime assignment → exact actionable trades → per-regime economics/calibration → quality gate → artifact runtime validation`.

## 4. Baseline

- Python 3.13.5.
- `pip check`: FAILED only because shared environment has `moviepy 2.2.1` with Pillow 12.2.0; project does not depend on moviepy.
- compileall: PASSED.
- Ruff: PASSED.
- pytest: **790 passed, 8 skipped**.
- JavaScript syntax: PASSED.
- PostgreSQL integration and doctor: NOT RUN; no isolated database/operator configuration.

## 5. Confirmed defect

**HIGH — aggregate final-holdout metrics masked a losing traded regime.**

A deterministic cohort produced aggregate `+0.40 R` from ten UPTREND trades at `+1.0 R` and ten RANGE trades at `-0.20 R`. Existing actionable calibration, temporal uncertainty, symbol jackknife and correlation-cluster jackknife did not condition the result by ex-ante market state. A candidate could therefore pass while one regime generated systematically negative recommendations.

Existing tests missed the defect because they checked aggregate, temporal, symbol and dependence-cluster dimensions separately, but did not stratify exact actionable rows by decision-time regime.

## 6. Diff

Production:

- `app/ml/training.py`: development-only threshold, regime builder, arithmetic validator and metrics.
- `app/ml/lifecycle.py`: per-traded-regime activation limits and diagnostics.
- `app/ml/runtime.py`: mandatory structural evidence validation.
- `app/__init__.py`, `pyproject.toml`: version 1.45.0.

Tests:

- Added `tests/unit/test_policy_market_regime_robustness_2026_07_07.py`.
- Added reusable valid regime evidence and synchronized current artifact/lifecycle fixtures.

Docs:

- README, CHANGELOG, PATCH_1.45.0, QA, SPEC_COMPLIANCE, TRACEABILITY and this report.

No migration or environment variable was added.

## 7. Red → green

Command on untouched 1.44.0:

```bash
python -m pytest -q tests/unit/test_policy_market_regime_robustness_2026_07_07.py
```

Result: **6 failed, 1 passed**. The passing case demonstrated the masking effect; failures showed missing builder, gate and runtime contracts.

Same command after implementation: **7 passed**.

## 8. Compatibility

- Policy metric schema: v21 → v22.
- Pre-1.45 artifacts intentionally fail closed and require retraining.
- No DB migration, API or `.env` action.
- Advisory-only, read-only Bybit and PostgreSQL-only boundaries preserved.

## 9. Post-check

- compileall: PASSED.
- Ruff: PASSED.
- full pytest: **797 passed, 8 skipped**.
- JavaScript syntax: PASSED.
- one Alembic head: `0017_model_artifact_blobs`.

## 10. Not verified

- Full PostgreSQL training/promotion/runtime cycle.
- Live Bybit ingestion/publication.
- Forward stability of regime thresholds.
- Per-symbol-by-regime minimum sample/calibration.
- Causal explanation of historical losses or proof of profitability.

## 11. Residual risks

- Regime classification is statistical and deliberately simple.
- Rare strategies may trade only one regime; this release does not force false diversification.
- Five observations are a minimum integrity floor, not strong statistical evidence by themselves; aggregate holdout, bootstrap, walk-forward and other gates remain mandatory.
- Exact historical fills and sub-hour path remain unavailable.

## 12. Rollback

Stop trainer/worker, restore 1.44.0 code and restart. Artifacts trained under v22 must not be relabeled as v21; rollback requires an artifact genuinely compatible with 1.44.0 or baseline fail-closed operation.

## 13. Recommended next work package

Add per-symbol-by-regime support/calibration diagnostics with hierarchical shrinkage or preregistered minimum cells, avoiding a combinatorial sparse-cell gate.
