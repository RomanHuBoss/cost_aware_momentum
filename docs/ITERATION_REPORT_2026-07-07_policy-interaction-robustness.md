# Iteration report — policy interaction robustness

## 1. Input

- Archive: `cost_aware_momentum-1.46.0-policy-direction-robustness.zip`
- SHA-256: `aaa91298e7f92d0b4e8e59acd85a3f30c754dd79cad630907adb1d0d65d29b1f`
- Source version: 1.46.0
- Python requirement: >=3.12; executed on 3.13.5
- Alembic head: `0017_model_artifact_blobs`
- Source inventory before the new regression: 98 production Python files, 112 test Python files, 24 documentation files and 17 migrations

## 2. Objective and acceptance criteria

After this iteration, normal activation and runtime loading must reject a candidate when a sufficiently supported `symbol × direction × market regime` cell is harmful or poorly calibrated, even if aggregate, per-symbol, per-direction and per-regime evidence remains positive.

Acceptance criteria:

1. Cells are formed only from exact actionable trades after overlap filtering.
2. Market regime assignment is identical to the existing development-only regime contract.
3. Cells with at least five trades are checked separately.
4. Smaller cells are not silently ignored; they are pooled into one deterministic sparse tail.
5. A non-empty sparse pool must have at least five aggregate trades and pass the same economics/calibration limits.
6. Counts, fractions, weighted pool metrics, canonical order and extrema are arithmetically validated.
7. Interaction symbol/direction/regime sets match existing marginal evidence.
8. Missing or malformed evidence blocks activation and runtime loading.
9. Existing safety and economic thresholds remain unchanged.

## 3. Sources and affected flow

Read: `README.md`, `CHANGELOG.md`, `PATCH_1.46.0.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `pyproject.toml`, `app/ml/training.py`, `app/ml/lifecycle.py`, `app/ml/runtime.py`, shared artifact fixtures and related policy tests.

Affected flow:

`final holdout directional scenarios → policy selection → EV/RR actionability → overlap filter → exact actionable trades → market-regime assignment → symbol × direction × regime cells → supported cells + sparse pool → quality gate → artifact metrics → runtime validator`.

## 4. Baseline

- `python --version`: PASSED, Python 3.13.5.
- `python -m pip check`: FAILED only because the shared environment has `moviepy 2.2.1` with incompatible Pillow 12.2.0; the project does not depend on moviepy.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: PASSED, 804 passed and 8 skipped.
- `node --check web/js/app.js`: PASSED.

`manage.py doctor` and PostgreSQL integration tests were not run because no isolated operator/test database was available.

## 5. Confirmed defect

### HIGH — marginal robustness masks a harmful interaction cell

Locations: `app/ml/training.py::evaluate_policy_model`, `app/ml/lifecycle.py::evaluate_quality_gate`, `app/ml/runtime.py::ModelRuntime.load`.

The existing release evaluated symbols, directions and regimes independently. A deterministic 40-trade example contained:

- aggregate mean `+0.70 R`;
- minimum symbol mean `+0.40 R`;
- minimum direction mean `+0.40 R`;
- minimum regime mean `+0.40 R`;
- `BTCUSDT × LONG × UPTREND` mean `-0.20 R`.

Expected: the candidate is rejected because a sufficiently supported exact policy cell is harmful.

Actual in 1.46.0: no interaction evidence or gate existed; the candidate could pass all marginal checks.

Existing tests did not catch the defect because they tested each marginal partition separately.

## 6. Change plan and actual diff

Production:

- `app/ml/training.py`: shared regime-classification helper; interaction evidence builder/validator; sparse pooling; policy metric schema v24.
- `app/ml/lifecycle.py`: supported-cell and sparse-pool quality gates; exact marginal-set consistency; diagnostics.
- `app/ml/runtime.py`: mandatory evidence and set-consistency validation.
- `app/__init__.py`, `pyproject.toml`: version 1.47.0.

Tests:

- added `tests/unit/test_policy_interaction_robustness_2026_07_07.py`;
- added shared valid interaction evidence;
- updated current artifact/lifecycle fixtures to policy schema v24;
- synchronized the symbol-jackknife acceptance fixture with exact interaction symbols.

Documentation:

- `README.md`, `CHANGELOG.md`, `PATCH_1.47.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this report and `SHA256SUMS`.

No migration, API or environment-variable change.

## 7. Red → green evidence

Original seven-test command on untouched 1.46.0:

```bash
python -m pytest -q tests/unit/test_policy_interaction_robustness_2026_07_07.py
```

Initial result: `6 failed, 1 passed`.

The passing test independently demonstrated the interaction masking. Failures proved the missing calculation, gate and runtime contract.

After implementation, the original set passed. Two additional green regressions were then added for an under-supported sparse pool and marginal symbol-set mismatch. Final file result: `9 passed`.

## 8. Compatibility

- Alembic head remains `0017_model_artifact_blobs`.
- No `.env` action required.
- Policy metric schema changed from v23 to v24.
- Pre-1.47 artifacts are deliberately incompatible and require retraining.
- Existing symbol, cluster, regime and direction evidence remains mandatory.

## 9. Post-check

- Interaction regression: 9 passed.
- Focused interaction/lifecycle/runtime: 26 passed.
- Full suite: 813 passed, 8 skipped.
- Ruff: passed.
- compileall: passed.
- JavaScript syntax: passed.
- Alembic heads: one, `0017_model_artifact_blobs`.

## 10. Not verified

- Full training/promotion/runtime cycle on operator PostgreSQL.
- PostgreSQL integration tests.
- Live Bybit ingestion and publication.
- Interaction evidence on actual historical and forward recommendations.
- Partial fills, queue position, operator latency and forward profitability.

## 11. Residual risks

The sparse pool prevents silent omission and a combinatorial family of tiny tests, but a harmful individual cell with fewer than five observations can be masked by other profitable cells inside the same pool. Five trades are not strong statistical power. The partition is descriptive and not causal.

## 12. Rollback

Stop trainer/worker/API, restore release 1.46.0 and restart. No database downgrade is required. Artifacts trained under v24 must not be loaded by 1.46.0; reactivate only an artifact compatible with the restored release.

## 13. Recommended next work package

Add prospective production monitoring for the same interaction buckets, with maturity-corrected outcomes and minimum-support rules, so a cell that was acceptable in final holdout but degrades in production can quarantine the exact active version without interpreting tiny samples as critical drift.
