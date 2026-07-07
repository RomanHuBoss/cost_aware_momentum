# Iteration report — policy-actionable calibration integrity

Date: 2026-07-07
Release: 1.42.0

## 1. Input archive

- Archive: `cost_aware_momentum-1.41.0-policy-selected-calibration-integrity.zip`
- SHA-256: `954508d3490e5dd08fd6776aaf9c3ec960a9795322ca40fc1b9cca3319d161a6`
- Source version: 1.41.0
- Source Alembic head: `0017_model_artifact_blobs`

## 2. Iteration objective and acceptance criteria

Objective:

> After this iteration, normal activation and runtime loading must require valid calibration evidence for the exact final-holdout observations that become policy trades after actionability and overlap filtering, so non-traded observations cannot mask overconfidence in rare recommendations.

Acceptance criteria:

1. Policy evaluation calculates actionable calibration after all trade-selection filters.
2. Actionable rows equal `policy_trades` exactly.
3. Existing absolute log-loss and multiclass-Brier limits apply to actionable calibration.
4. Missing, malformed, non-finite or inconsistent evidence fails closed.
5. Runtime rejects artifacts without the current actionable calibration contract.
6. No ML, policy, spread, EV/RR, risk or freshness threshold is relaxed.
7. New regressions demonstrate red → green and the complete available suite remains green.

## 3. Sources read and affected data flow

Reviewed:

- `README.md`, `CHANGELOG.md`, `PATCH_1.40.0.md`, `PATCH_1.41.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- `pyproject.toml` and `.env.example`;
- `app/ml/training.py`, `app/ml/lifecycle.py`, `app/ml/runtime.py`;
- policy, calibration, artifact and runtime regression tests.

Affected flow:

```text
final holdout LONG/SHORT probabilities
→ one selected direction per opportunity
→ economic actionability filter
→ single-active-trade overlap filter
→ actual policy-trade rows
→ actionable log loss/Brier
→ quality gate
→ immutable artifact metrics
→ runtime validation
```

## 4. Baseline

After installing only the declared development extra from `pyproject.toml`:

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | FAILED — shared environment has unrelated `moviepy 2.2.1` / Pillow 12.2.0 conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 768 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |

`python manage.py doctor` and PostgreSQL integration tests were not run because no isolated test database/operator configuration was available. No operator database was accessed.

## 5. Confirmed defects

### DEFECT-1 — calibration selection bias after actionability — HIGH

Location: `app/ml/training.py::evaluate_policy_model`.

Expected: calibration used to authorize trading should describe the observations that actually become trades.

Actual: selected-direction calibration was calculated before actionability and overlap filtering. Correctly classified non-trades could dominate the average and hide severe overconfidence among rare trades.

Reproducer: 150 opportunities, of which 20 become trades. The old aggregate selected-direction evidence remains inside configured limits while actual-trade log loss exceeds 4 and Brier exceeds 1.5.

Impact: a candidate could pass activation while its published recommendations are materially less calibrated than the larger rejected cohort.

Why existing tests missed it: tests verified selected direction versus both-direction averages, but did not separate selected opportunities from the exact post-filter trade subset.

### DEFECT-2 — activation gate omitted actual-trade calibration — HIGH

Location: `app/ml/lifecycle.py::evaluate_quality_gate`.

Expected: exact actionable-trade calibration must satisfy the same absolute calibration limits.

Actual: no actionable calibration schema, metric or count was required.

Impact: the gate could approve the defect described above without any explicit diagnostic reason.

### DEFECT-3 — artifact/runtime did not bind actionable evidence — HIGH

Location: `app/ml/runtime.py::ModelRuntime.load`.

Expected: an artifact must prove that actionable calibration corresponds exactly to `policy_trades`.

Actual: pre-1.42 artifacts could load without such evidence.

Impact: stale semantics could survive deployment even after the trainer/gate was strengthened.

## 6. Plan and actual diff

Production:

- `app/ml/training.py` — calculate actionable calibration and raise policy metric schema to v19.
- `app/ml/lifecycle.py` — enforce schema, exact row count and absolute limits.
- `app/ml/runtime.py` — require current policy/actionable evidence during artifact loading.
- `app/__init__.py`, `pyproject.toml` — version 1.42.0.

Tests:

- new `tests/unit/test_policy_actionable_calibration_gate_2026_07_07.py`;
- new reusable `tests/model_artifact_metrics.py`;
- current-schema fields added to valid artifact/gate fixtures without weakening negative tests.

Release/docs:

- `README.md`, `CHANGELOG.md`, `PATCH_1.42.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this report and `SHA256SUMS`.

No migration, API contract or `.env` change.

## 7. Red → green evidence

Command on untouched 1.41.0:

```text
PYTHONPATH=. python -m pytest -q tests/unit/test_policy_actionable_calibration_gate_2026_07_07.py
```

Red result:

```text
6 failed, 1 passed
```

The passing test independently demonstrated the numerical masking effect. The six failed tests were the absent production guards.

Green result after implementation:

```text
7 passed
```

Targeted manually constructed runtime artifacts were then reconciled with the current schema:

```text
4 passed
```

## 8. Compatibility

- Database migration: none.
- Alembic head: unchanged, `0017_model_artifact_blobs`.
- `.env`: unchanged.
- API: unchanged.
- Advisory-only/read-only Bybit boundary: unchanged.
- Artifact compatibility: intentionally stricter. Pre-1.42 artifacts lack actionable calibration evidence and are rejected fail-closed; retraining is required.

## 9. Post-change checks

| Command | Result |
|---|---|
| `python -m pip check` | FAILED — same unrelated shared moviepy/Pillow conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| actionable regression suite | PASSED — 7 passed |
| targeted runtime compatibility | PASSED — 4 passed |
| `python -m pytest -q` | PASSED — 775 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — one head |

## 10. Not verified

- Isolated PostgreSQL migration/integration execution.
- Full training and activation on the operator data.
- Live Bybit inference and forward outcomes.
- Calibration stability by symbol, market regime or walk-forward fold.
- Exact historical fills, queue position, partial fills and sub-hour execution.

## 11. Residual risks and limitations

Actionable calibration on a finite holdout is a necessary safety check, not proof of positive expected value. A small number of trades can still yield wide uncertainty. The existing minimum trade/cohort, confidence-bound, walk-forward and experiment-governance gates remain necessary.

The current patch evaluates aggregate actionable calibration over the final holdout. Concentration of errors in one symbol or one regime remains possible and should be treated as the next econometric work package.

## 12. Rollback procedure

1. Stop trainer and inference worker.
2. Restore the 1.41.0 release files.
3. Do not force-activate a 1.42 candidate under 1.41 semantics.
4. Restart services only after confirming the intended active artifact contract.

No database downgrade is required because this iteration has no migration.

Rollback reopens the confirmed calibration-selection defect and is not recommended for normal operation.

## 13. Recommended next work package

Add dependence-aware actionable calibration stability across walk-forward folds, symbols and time regimes. The next gate should prevent one symbol or short market regime from supplying most of the apparent actionable calibration/edge while preserving minimum effective sample-size and block-dependence constraints.
