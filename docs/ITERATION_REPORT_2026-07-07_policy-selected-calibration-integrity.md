# Iteration report — policy-selected calibration integrity

## 1. Input

- Archive: `cost_aware_momentum-1.40.0-decision-time-entry-anchoring.zip`
- SHA-256: `28e94465570926345a1c3550a1106af0534d19b465afd8e13180092a7d1fd13d`
- Source version: 1.40.0
- Source Alembic head: `0017_model_artifact_blobs`

## 2. Goal and acceptance criteria

After this iteration, normal activation must evaluate probability calibration on the exact LONG/SHORT direction selected by the policy, and its immutable evidence counts must be internally consistent.

Acceptance criteria:

1. selected cohort cannot be inferred from all-direction probabilities;
2. poor selected-direction log loss blocks activation;
3. poor selected-direction Brier blocks activation;
4. final-holdout directional rows equal twice policy opportunities;
5. selected calibration rows equal policy opportunities;
6. immutable drift-reference rows equal final-holdout rows;
7. all existing unit/static checks remain green.

## 3. Sources and data flow

Read: README, CHANGELOG, recent PATCH files, pyproject, architecture/QA/compliance/traceability/model-card/configuration/security/operator documents, ML training/drift/lifecycle/runtime modules and related tests.

Audited flow:

`final holdout LONG+SHORT probabilities → policy direction selection → selected-direction calibration → immutable drift reference → quality gate → artifact activation → production drift monitor`.

## 4. Baseline

- Python 3.13.5.
- `pip check`: FAILED only because shared-environment `moviepy 2.2.1` requires Pillow <12 while Pillow 12.2.0 is installed.
- compileall: PASSED.
- Ruff: PASSED.
- pytest: 762 passed, 8 skipped.
- Node syntax: PASSED.
- PostgreSQL integration: NOT RUN; no isolated test database.

## 5. Confirmed defects

### HIGH — activation ignored selected-direction calibration

`evaluate_policy_model()` computed `policy_selected_log_loss` and `policy_selected_multiclass_brier`, but `evaluate_quality_gate()` checked only global metrics across both directional counterfactual rows. The unselected side could mask overconfidence in the actual recommendation direction.

### HIGH — selected evidence could be implicitly fabricated

`build_production_drift_reference()` calculated calibration from all supplied probability rows even when the caller declared the selected-direction schema. No independent selected cohort was required.

### HIGH — evidence cardinalities were unconstrained

The gate did not bind holdout directional rows, selected opportunities, selected calibration rows and drift-reference rows. Impossible evidence combinations could pass.

Existing tests focused on global calibration and policy economics; they did not adversarially alter selected calibration or cohort counts.

## 6. Diff

Production:

- `app/ml/drift.py`
- `app/ml/lifecycle.py`
- `app/__init__.py`
- `pyproject.toml`

Tests:

- new `tests/unit/test_policy_selected_calibration_gate_2026_07_07.py`
- parameterized `tests/drift_reference.py`
- reconciled affected lifecycle, drift, recovery, uncertainty, density and econometric fixtures.

Documentation/release:

- README, CHANGELOG, PATCH 1.41.0, QA, compliance, traceability, this report and SHA256SUMS.

No migration or environment change.

## 7. Red → green

Command on untouched 1.40.0 with the new regression test:

```text
PYTHONPATH=. python -m pytest -q tests/unit/test_policy_selected_calibration_gate_2026_07_07.py
```

Red: `6 failed` for the intended missing guards.

Same command after implementation: `6 passed`.

## 8. Compatibility

The production-drift reference schema is v3 and selected calibration schema is v2. Runtime validators therefore reject older artifacts instead of interpreting old evidence under the new contract. Retraining is required. Database and `.env` contracts are unchanged.

## 9. Post-check

- compileall: PASSED.
- Ruff: PASSED.
- regression suite: 6 passed.
- full pytest: 768 passed, 8 skipped.
- Node syntax: PASSED.
- Alembic: one head, `0017_model_artifact_blobs`.
- `pip check`: same unrelated shared-environment conflict.

## 10. Not verified

- PostgreSQL integration and migration smoke test.
- Full training/activation with operator data.
- Live production-drift collection for a 1.41 artifact.
- Economic profitability or causal explanation of all prior losses.

## 11. Residual risks

Historical execution remains a constrained hourly proxy. Selected calibration remains finite-sample and may degrade under regime shift. Queue position, partial fills, sub-hour path and operator latency are not fully modeled.

## 12. Rollback

Stop API/worker/trainer, restore 1.40.0 code and restart. No database rollback is needed. A model trained under schema v3/v2 will be rejected by 1.40 runtime; activate only an artifact compatible with the rolled-back release. Rollback reopens the selected-calibration defect and is not recommended for normal operation.

## 13. Recommended next work package

Audit whether candidate/incumbent comparison and experiment-family selection apply multiplicity/dependence controls to the same policy-selected probability cohort, including symbol/time clustered calibration uncertainty. Do not lower activation thresholds before that evidence exists.
