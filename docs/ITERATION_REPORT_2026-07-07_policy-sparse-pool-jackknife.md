# Iteration report — policy sparse-pool jackknife

## 1. Input

- Archive: `cost_aware_momentum-1.47.0-policy-interaction-robustness.zip`
- SHA-256: `efc3c88df6467cab3d2f135ba59202c1a1ae59521f5328a0c86cb078e14a73e8`
- Source version: 1.47.0
- Alembic head: `0017_model_artifact_blobs`

## 2. Goal and acceptance criteria

After this iteration, a positive pooled tail of under-supported `symbol × direction × regime` cells must not authorize activation when all remaining sparse evidence becomes under-supported, unprofitable or poorly calibrated after removing any one sparse cell.

Acceptance criteria:

1. exact leave-one-cell-out results are calculated for every sparse cell;
2. omitted identity, counts, fractions and metrics are immutable and arithmetically validated;
3. every residual has at least five trades;
4. every sufficiently supported residual passes existing mean R, log-loss and Brier limits;
5. runtime rejects legacy or malformed evidence;
6. no existing policy/risk threshold is relaxed;
7. full unit/static suite remains green.

## 3. Sources and data flow

Read: `README.md`, `CHANGELOG.md`, recent patch notes, `pyproject.toml`, `.env.example`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, the 1.47 iteration report, `app/ml/training.py`, `app/ml/lifecycle.py`, `app/ml/runtime.py` and related tests.

Changed flow:

`exact actionable trades → interaction cells → sparse pool → remove each sparse cell → residual economics/calibration → quality gate → artifact/runtime validation`.

The archive does not contain several filenames named in the generic master prompt (`docs/ARCHITECTURE.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`); no nonexistent files were invented.

## 4. Baseline

- Python 3.13.5.
- `pip check`: failed only because shared `moviepy 2.2.1` requires Pillow below 12 while the environment has Pillow 12.2.0.
- compileall: passed.
- Ruff: passed.
- pytest: 813 passed, 8 skipped.
- JavaScript syntax: passed.
- PostgreSQL integration and `manage.py doctor`: not run; no isolated database/operator configuration was available.

## 5. Confirmed defect

**Severity: high.**

1.47 evaluated every cell with at least five trades separately and pooled all smaller cells. The gate checked only the pool aggregate. A deterministic cohort with sparse cell contributions `4 × +1.00 R`, `3 × -0.20 R`, `3 × -0.20 R` had pooled mean `+0.28 R`. Removing the profitable four-trade cell left six trades at `-0.20 R`.

Expected: a sparse pool must not pass solely because one tiny cell provides all edge.

Actual: the pool passed positive economics/calibration; no residual sensitivity existed.

Existing tests covered a negative aggregate pool and insufficient aggregate support, but not concentration inside a positive pool.

## 6. Diff

Production:

- `app/ml/training.py`: v25/v2 schemas, exact residual builder and strict validator.
- `app/ml/lifecycle.py`: residual support/economics/calibration gates and report fields.
- `app/__init__.py`, `pyproject.toml`: version 1.48.0.

Tests:

- added `tests/unit/test_policy_sparse_pool_jackknife_2026_07_07.py`;
- updated current artifact and interaction fixtures for the v25/v2 contract.

Documentation:

- `README.md`, `CHANGELOG.md`, `PATCH_1.48.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this report and `SHA256SUMS`.

No migration or configuration variable was added.

## 7. Red → green

Command:

```bash
PYTHONPATH=. python -m pytest -q tests/unit/test_policy_sparse_pool_jackknife_2026_07_07.py
```

Untouched 1.47.0: `6 failed, 1 passed`.

After implementation: `7 passed`.

The independent passing red test demonstrates the aggregate/residual contradiction; the six initial failures cover missing builder evidence, activation reasons, minimum residual support, strict validator behavior, a valid passing case and runtime rejection.

## 8. Compatibility and rollback

- No DB migration.
- No `.env` action.
- Pre-1.48 artifacts lack mandatory sparse jackknife evidence and are rejected fail-closed.
- Rollback: stop trainer/worker, restore the 1.47 release and its compatible artifact. Do not edit schema strings in an artifact.

## 9. Post-check

- New regression: 7 passed.
- Focused compatibility: 35 passed.
- Full pytest: 820 passed, 8 skipped.
- Ruff, compileall, JavaScript syntax: passed.
- One Alembic head: `0017_model_artifact_blobs`.

## 10. Not verified

- Full PostgreSQL training and activation.
- Live Bybit ingestion/publication.
- Forward performance of residual sparse cohorts.
- Statistical power of individual tiny cells.
- Economic profitability.

## 11. Residual risks

The jackknife proves that no single sparse cell is indispensable to the pooled result. It does not prove each tiny cell is safe. Several profitable cells can still mask several harmful cells. Solving that honestly requires more prospective observations or a preregistered hierarchical partial-pooling model with out-of-sample validation.

## 12. Next work package

Add stage-by-stage trainer-history attrition diagnostics that separately report loaded candles, continuity, context, universe/spread replay, labels, temporal split and final holdout. This addresses the operator-visible `4/1206` ambiguity without weakening temporal validation.
