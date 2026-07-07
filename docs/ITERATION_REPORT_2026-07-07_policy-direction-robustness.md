# Iteration report — policy directional robustness

## 1. Input

- Archive: `cost_aware_momentum-1.45.0-policy-market-regime-robustness.zip`
- SHA-256: `29156245b1ca81c66acaf2c926de4298dbd471cf0e3f2c6510f67967d97a2788`
- Source version: 1.45.0
- Python requirement: >=3.12; executed on 3.13.5
- Alembic head: `0017_model_artifact_blobs`
- Source inventory: 98 production Python files, 111 test Python files, 23 documentation files, 17 migrations

## 2. Iteration objective and acceptance criteria

After this iteration, normal model activation and runtime loading must reject a candidate when either actually traded LONG or SHORT sub-policy is under-supported, non-positive or outside the existing calibration limits, even if aggregate, symbol, cluster and market-regime evidence remains acceptable.

Acceptance criteria:

1. Exact actionable trades are partitioned only after actionability and overlap filtering.
2. LONG and SHORT economics are recomputed on the complete observed opportunity clock.
3. No-trade hours remain explicit zero-return cohorts.
4. Trade counts, fractions, calibration rows and summaries are arithmetically validated.
5. Each traded direction requires at least five trades and positive mean R.
6. Existing log-loss and multiclass-Brier limits apply separately to each traded direction.
7. Missing or malformed direction evidence blocks activation and runtime loading.
8. Existing safety, advisory-only, PostgreSQL-only and read-only boundaries remain unchanged.

## 3. Sources and affected data flow

Read: `README.md`, `CHANGELOG.md`, `PATCH_1.45.0.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `pyproject.toml`, `app/ml/training.py`, `app/ml/lifecycle.py`, `app/ml/runtime.py`, artifact fixtures and related policy tests.

Affected flow:

`final holdout directional scenarios → policy direction selection → EV/RR actionability → overlap filter → exact actionable trades → LONG/SHORT opportunity-clock economics and calibration → quality gate → artifact metrics → runtime validator`.

## 4. Baseline

After installing only declared project/dev dependencies:

- `python -m pip check`: FAILED only because shared environment has `moviepy 2.2.1` with incompatible Pillow 12.2.0; project does not depend on moviepy.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: PASSED, 797 passed and 8 skipped.
- `node --check web/js/app.js`: PASSED.

`manage.py doctor` and PostgreSQL integration tests were not run because no isolated operator/test database was available.

## 5. Confirmed defect

### HIGH — profitable direction masks harmful opposite direction

Location: `app/ml/training.py::evaluate_policy_model`, `app/ml/lifecycle.py::evaluate_quality_gate`, `app/ml/runtime.py::ModelRuntime.load`.

Before the fix, metrics covered aggregate actionable calibration/economics, symbols, correlation clusters and market regimes, but did not evaluate LONG and SHORT separately after policy selection.

Reproducer:

- 10 LONG trades at `+1.0 R`;
- 10 SHORT trades at `-0.20 R`;
- aggregate mean `+0.40 R`;
- LONG mean on full opportunity clock `+0.50 R`;
- SHORT mean on full opportunity clock `-0.10 R`.

Expected: candidate rejected because the traded SHORT policy is harmful.
Actual in 1.45.0: no direction evidence or gate existed; candidate could pass.

Existing tests did not catch the defect because they checked selected/actionable calibration, symbol/cluster concentration and regimes independently, not the directional decomposition of the exact traded cohort.

## 6. Change plan and actual diff

Production:

- `app/ml/training.py`: added direction evidence builder/validator; integrated evidence into policy metrics; schema v23.
- `app/ml/lifecycle.py`: enforced minimum support, positive economics and calibration per traded direction; added gate diagnostics.
- `app/ml/runtime.py`: mandatory direction evidence validation before loading artifact.
- `app/__init__.py`, `pyproject.toml`: version 1.46.0.

Tests:

- added `tests/unit/test_policy_direction_robustness_2026_07_07.py`;
- updated shared artifact/lifecycle metrics fixtures to current v23 evidence.

Documentation:

- `README.md`, `CHANGELOG.md`, `PATCH_1.46.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this iteration report and `SHA256SUMS`.

No migration, API or environment-variable change.

## 7. Red → green evidence

Command on untouched 1.45.0:

```bash
python -m pytest -q tests/unit/test_policy_direction_robustness_2026_07_07.py
```

Result: `6 failed, 1 passed`.

The passing test independently demonstrated aggregate `+0.40 R` with negative SHORT. Failures proved the missing calculation, gate and runtime contract.

After implementation: `7 passed`.

## 8. Compatibility

- Alembic head remains `0017_model_artifact_blobs`.
- No `.env` actions required.
- Policy metric schema changed from v22 to v23.
- Pre-1.46 artifacts are deliberately incompatible and require retraining.
- One-direction strategies remain allowed; only directions actually traded are subjected to the minimum-support/economics/calibration checks.

## 9. Post-check

- Direction regression: 7 passed.
- Focused lifecycle/runtime: 36 passed.
- Full suite: 804 passed, 8 skipped.
- Ruff: passed.
- compileall: passed.
- JavaScript syntax: passed.
- Alembic heads: one, `0017_model_artifact_blobs`.

## 10. Not verified

- Full training/promotion/runtime cycle on operator PostgreSQL.
- PostgreSQL integration tests.
- Live Bybit ingestion and publication.
- Direction evidence on real historical/forward recommendations.
- Fill latency, queue position, partial fills and economic profitability.

## 11. Residual risks

A direction can pass overall while a particular symbol × direction × regime cell is harmful. Very sparse directions are intentionally blocked below five trades, but this minimum does not establish strong statistical power. The test is robustness evidence, not proof of future edge.

## 12. Rollback

Stop trainer/worker/API, restore release 1.45.0 and its configuration, then restart. No database downgrade is required. Artifacts trained under v23 must not be loaded by 1.45.0; reactivate only an artifact compatible with the restored release.

## 13. Recommended next work package

Add preregistered symbol × direction × regime interaction diagnostics with multiplicity-aware minimum support, without creating a combinatorial gate that makes all sparse candidates impossible to evaluate.
