# Iteration report — policy symbol jackknife robustness

## 1. Input

- Archive: `cost_aware_momentum-1.42.0-policy-actionable-calibration-integrity.zip`
- SHA-256: `bea0a5c3be5e02829638574d1903d1cfd6003bde0fee4e42dacc7696f23c5a85`
- Source version: 1.42.0
- Target version: 1.43.0

## 2. Goal and acceptance criteria

After this iteration, normal activation must fail closed when final-holdout profitability depends on any one traded symbol. Acceptance required exact post-policy jackknife calculation, immutable evidence validation, runtime rejection of legacy/malformed evidence, red-to-green tests and no regression of existing gates.

## 3. Data flow reviewed

`final holdout probabilities → direction selection → EV/RR actionability → overlap filtering → realized trade R → opportunity cohorts → quality gate → artifact → runtime`.

Reviewed sources included README, CHANGELOG, PATCH_1.40–1.42, QA, SPEC_COMPLIANCE, TRACEABILITY, training/lifecycle/runtime modules and related quant/artifact tests.

## 4. Baseline

After installing declared `psycopg` and `ruff`: compileall PASSED, Ruff PASSED, pytest **775 passed / 8 skipped**, JavaScript syntax PASSED. `pip check` remained failed only because shared `moviepy` conflicts with installed Pillow. PostgreSQL integration was not run.

## 5. Confirmed defect

**HIGH — single-symbol edge concentration.** `evaluate_policy_model` only emitted aggregate cohort economics. A deterministic two-symbol example returned aggregate `+0.4 R`; removal of the profitable symbol returned `-0.2 R`. Existing temporal bootstrap, walk-forward and actionable calibration did not encode this cross-symbol counterfactual. Existing tests did not remove symbols and recompute portfolio weighting.

## 6. Change

- Added `POLICY_SYMBOL_ROBUSTNESS_SCHEMA`.
- Added exact leave-one-symbol-out recomputation on the observed opportunity clock.
- Added strict evidence validator shared by lifecycle and runtime.
- Added quality-gate reasons for invalid evidence, fewer than two traded symbols and non-positive worst jackknife result.
- Raised policy metric schema to v20.
- Updated test artifact fixtures and release documentation.

No migration, config variable or public API changed.

## 7. Red → green

Command: `python -m pytest -q tests/unit/test_policy_symbol_jackknife_robustness_2026_07_07.py`.

- Untouched 1.42.0: **6 failed, 1 passed**.
- 1.43.0 implementation: **7 passed**.

## 8. Post-check

- compileall: PASSED
- Ruff: PASSED
- pytest: **782 passed, 8 skipped**
- Node syntax: PASSED
- Alembic: one unchanged head `0017_model_artifact_blobs`

## 9. Unverified

No isolated PostgreSQL integration run, no full training on operator data, no live Bybit run and no forward profitability evidence.

## 10. Residual risks

The test removes one symbol at a time only. Correlated symbol groups, market regimes, per-symbol calibration and live execution quality remain separate questions.

## 11. Rollback

Stop trainer/worker/API, restore 1.42.0 code and retain the PostgreSQL database because no migration occurred. A 1.43 artifact should not be forced into 1.42 runtime; restore a compatible artifact or remain on fail-closed baseline.

## 12. Recommended next work package

Add regime- and correlation-cluster stability for the actionable final-holdout cohort without weakening the new single-symbol jackknife.
