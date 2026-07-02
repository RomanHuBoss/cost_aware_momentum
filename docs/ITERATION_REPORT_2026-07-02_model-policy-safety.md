# Iteration report — model-policy safety

Date: 2026-07-02

## 1. Input and version

- Input ZIP: `cost_aware_momentum-main(1).zip`.
- Input SHA-256: `200a4bca62367d97f4712816332dfb815cacdafafb29246bea7ee5bfd03087de`.
- Source version: `1.8.32`; result version: `1.8.33`.
- Python requirement: `>=3.12`.
- Alembic migrations: 8; one head `0008_outcome_path_unavailable`.

## 2. Goal and acceptance criteria

After this iteration an uncalibrated deterministic baseline must remain diagnostic-only, all live/promotion TIMEOUT economics must use one explicit persisted assumption, and independent cohort evidence must have its own promotion threshold.

Acceptance criteria:

1. Baseline plan is `NO_TRADE` by default even when raw RR/EV passes.
2. Legacy baseline plan cannot be accepted.
3. Production rejects an actionable-baseline override.
4. TIMEOUT assumption is validated, shared and persisted across signal, plan, acceptance, serialization, promotion evaluation and the backtest default.
5. Raw policy trades and independent decision-time cohorts have separate settings and gate evidence.
6. Existing tests remain green; no migration or advisory-only boundary change.

## 3. Sources and data flow reviewed

Read: README, CHANGELOG, latest patch/report history, pyproject, `.env.example`, architecture, QA, compliance, traceability, model card, configuration, security, incident/operator docs and the embedded specification DOCX.

Reviewed flow:

`confirmed candles + current ticker/spec` → feature snapshot → baseline/artifact directional probabilities → exact cost-aware LONG/SHORT scenario → `MarketSignal` → capital/account-dependent `ExecutionPlan` → fresh acceptance validation → API/UI; and separately `training holdout` → policy economics → absolute/relative quality gate → guarded activation.

## 4. Baseline

Isolated venv commands:

- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: PASSED — 410 passed, 4 skipped, 19 warnings.
- `node --check web/js/app.js`: PASSED.

## 5. Confirmed findings

### Critical — baseline provenance did not participate in execution policy

`ModelRuntime` marks fallback as `uncalibrated-baseline-v1`, but `create_execution_plan` evaluated only geometry, freshness, risk and RR/EV. The warning had no blocking semantics. Acceptance also trusted an already actionable plan without checking model provenance.

Minimal reproduction with neutral baseline probabilities and current defaults:

| ATR fraction | net RR | EV/R |
|---:|---:|---:|
| 0.002 | 0.6386 | -0.4041 |
| 0.005 | 1.1782 | -0.1778 |
| 0.010 | 1.4822 | -0.0503 |
| 0.020 | 1.6773 | 0.0315 |
| 0.050 | 1.8131 | 0.0885 |

At 5% ATR the uncalibrated fallback crossed both default gates. This explains a credible mechanism for rare recommendations while no trained candidate is active. It does not prove that every reported loss came from this path.

### High — hidden TIMEOUT assumption

The gross TIMEOUT return `-0.002` affected EV and model promotion but was not a typed operator setting or independent snapshot field. The specification treats such figures as assumptions requiring calibration, not immutable market facts.

### Medium — trade/cohort gate coupling

`policy_cohorts` was compared with `AUTO_TRAIN_MIN_POLICY_TRADES`. The UI/status could show a cohort failure, but the operator could not configure the required independent sample count separately.

## 6. Changes

Production:

- `app/config.py`: new validated settings and production guard.
- `app/services/signals.py`: explicit timeout input; runtime/economics provenance persisted.
- `app/services/execution.py`: baseline classifier, plan block, legacy acceptance block, timeout parity and snapshot field.
- `app/api/serializers.py`: reconstructs economics using persisted timeout assumption.
- `app/ml/lifecycle.py`: shared timeout policy and independent cohort threshold.
- `app/api/v1/status.py`: exposes the relevant policy settings.
- `scripts/backtest.py`: inherits the shared TIMEOUT assumption unless an explicit CLI override is supplied.

Tests:

- `tests/unit/test_model_policy_safety_2026_07_02.py` (new).
- `tests/unit/test_execution_acceptance_safety.py`.
- `tests/unit/test_quant_policy_integrity_2026_06_30.py`.

Docs/release:

- version sources, README, CHANGELOG, `.env.example`, patch note, QA, configuration, model card, operator/security/compliance/traceability docs and this report.

## 7. Red → green evidence

Command:

`python -m pytest -q tests/unit/test_execution_acceptance_safety.py::test_unvalidated_baseline_plan_is_diagnostic_only tests/unit/test_quant_policy_integrity_2026_06_30.py::test_quality_gate_uses_independent_cohort_threshold tests/unit/test_model_policy_safety_2026_07_02.py`

Red: 4 failed — actual baseline status `ACTIONABLE`; cohort candidate rejected; timeout keyword unsupported; production override accepted.

Green: the focused suite passed after production changes. Full suite then passed with 416 tests.

## 8. Compatibility

- No DB migration.
- No endpoint removal or order-mutation functionality.
- New status fields are additive.
- Old `.env` is compatible through defaults.
- Old signal/plan snapshots use the previous `-0.002` fallback when no persisted assumption exists.
- Legacy baseline signals are detected through stored runtime metadata and version/calibration fallback.

## 9. Post-check

- pip check: PASSED.
- compileall: PASSED.
- Ruff: PASSED.
- pytest: PASSED — 416 passed, 4 skipped, 19 warnings.
- Node syntax: PASSED.
- Alembic: PASSED — one head.
- Doctor: environment failure only (`.env`, PostgreSQL binaries/server and secrets absent).
- Required integration suite: NOT RUN because no safe PostgreSQL test URL exists.

## 10. Not verified

- Real PostgreSQL integration and migration execution.
- User-specific historical decisions, accepted plans, fills and losses.
- Actual candidate gate payloads/artifacts from the running installation.
- Forward profitability and execution realism.

## 11. Residual risks

- A calibrated model can still be unprofitable out of sample; gates reduce but do not remove this risk.
- The current TIMEOUT default remains a hypothesis until independently calibrated.
- Historical market microstructure/funding and full walk-forward/drift/PBO/DSR remain incomplete.
- Model-training frequency does not create information; repeated daily failure can be correct rejection of weak/insufficient evidence.

## 12. Rollback

1. Stop API/worker/trainer.
2. Restore 1.8.32 source files; no DB downgrade is required.
3. Remove the three optional new `.env` keys if desired.
4. Restart services and verify current model/plan state. Note that rollback reopens actionable-baseline risk and is not recommended.

## 13. Recommended next work package

Build an operator-facing candidate rejection dossier from real PostgreSQL state: per-candidate absolute/relative gate values, independent cohort coverage, class distribution, regime/symbol slices and accepted-plan outcome attribution. This requires the running database/artifacts and should not be simulated from the source tree.
