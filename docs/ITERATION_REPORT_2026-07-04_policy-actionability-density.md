# Iteration Report — policy actionability density

Date: 2026-07-04

## 1. Input archive and baseline identity

- Input: `cost_aware_momentum-main.zip`.
- Input SHA-256: `faee7d0f484848c34c33970aa8be950e95782116d0e0fbd449d55f799b0afa6e`.
- Input version: `1.9.4`; result version: `1.9.5`.
- Python requirement: `>=3.12`; executed with Python 3.13.5.
- Alembic revisions: `0001` through `0009`; single head `0009_candle_receipt_availability`.
- Input release manifest: 180/180 files verified.
- Input tree contained no `.env`, secrets, virtualenv, cache, dump or real model artifact.

## 2. Iteration objective and acceptance criteria

Objective:

> After this iteration automatic promotion must fail closed when the final-holdout policy selects a statistically/operationally microscopic fraction of candidates or when its count/rate evidence is contradictory, proven by independent regression tests.

Acceptance criteria:

1. `policy_candidates`, `policy_trades` and `policy_trade_rate` are required, finite and arithmetically consistent.
2. Promotion requires a configurable positive minimum rate in addition to existing trade/cohort/economic gates.
3. A candidate with 80 trades out of 100,000 candidates is rejected under defaults.
4. A candidate exactly at the default 1% boundary remains eligible when every other gate passes.
5. Invalid threshold configuration fails at startup.
6. Threshold and observed evidence are visible in status/quality-gate diagnostics.
7. Existing tests remain green; advisory-only, PostgreSQL-only and active-incumbent safety are unchanged.

## 3. Sources read and data flow

Read before modification:

- `README.md`, `CHANGELOG.md`, `PATCH_1.9.2.md`, `PATCH_1.9.3.md`, `PATCH_1.9.4.md`;
- `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- relevant sections of `docs/source/Cost_aware_hourly_ML_momentum_specification.docx` concerning temporal validation, costs, promotion and forward evidence;
- ML features/labels/training/runtime/lifecycle, trainer, signals, execution, risk mathematics, status API/UI and their tests.

Affected flow:

`final holdout rows -> directional scenario/economic filtering -> one-direction-per-symbol/time selection -> overlap filtering -> policy_candidates/policy_trades/policy_trade_rate -> quality gate -> candidate registry/auto-activation -> status diagnostics`.

## 4. Baseline before changes

| Command | Status | Result |
|---|---|---|
| `.venv/bin/python --version` | PASSED | Python 3.13.5 |
| `.venv/bin/python -m pip check` | PASSED | no broken requirements |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `.venv/bin/python -m ruff check .` | PASSED | all checks passed |
| `.venv/bin/python -m pytest -q` | PASSED | 448 passed, 4 skipped, 55 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `.venv/bin/python -m alembic heads` | PASSED | `0009_candle_receipt_availability (head)` |
| `.venv/bin/python manage.py doctor` | FAILED / ENVIRONMENT | default secrets; PostgreSQL CLI/server unavailable |
| integration suite | NOT RUN | no isolated PostgreSQL URL/server |

## 5. Confirmed defect/gap and evidence

### CONFIRMED GAP — HIGH — promotion ignored actionability density

Production evidence before fix:

- `app/ml/training.py::evaluate_policy_model` emitted `policy_candidates` and `policy_trade_rate = policy_trades / policy_candidates`.
- `app/ml/lifecycle.py::evaluate_quality_gate` consumed `policy_trades`, independent cohorts, mean R, profit factor and drawdown, but never consumed candidate count or rate.

Minimal reproduction:

- holdout candidates: 100,000;
- policy trades: 80;
- trade rate: 0.0008 (0.08%);
- all existing ML/economic/trade/cohort point thresholds satisfied.

Expected under the user-visible requirement of a usable recommendation system: fail closed because the promoted policy is operationally microscopic.

Actual before fix: `passed=True`.

Impact:

- operational: an auto-activated model can almost never produce a tradable plan;
- econometric: evidence is selected from a tiny fraction of a large search surface and remains fragile to sampling/threshold choice;
- safety: a superficially positive point estimate may be promoted without an explicit frequency floor.

Existing tests missed the gap because their fixtures contained only absolute trade/cohort counts and did not represent the denominator.

No evidence was available to attribute specific realized losses or all `NO_TRADE` events to this gap. The externally claimed error counts were therefore not repeated as findings.

## 6. Plan and actual diff

Production/config:

- `app/config.py` — new validated threshold.
- `app/ml/lifecycle.py` — required count/rate evidence, consistency and minimum-density gate.
- `app/api/v1/status.py` — additive threshold diagnostic.
- `app/__init__.py`, `pyproject.toml` — version 1.9.5.
- `.env.example` — documented default.

Tests:

- new `tests/unit/test_policy_actionability_density_2026_07_04.py`;
- updated quality-gate fixtures in `test_model_artifact_recovery.py`, `test_model_lifecycle.py`, `test_quant_econometric_audit_2026_06_29.py`, `test_quant_integrity_2026_07_02.py`, `test_quant_policy_integrity_2026_06_30.py`, `test_training_evidence_integrity_2026_07_02.py` to include complete evidence.

Documentation/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.9.5.md`;
- `docs/CONFIGURATION.md`, `MODEL_CARD.md`, `OPERATOR_MANUAL.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, this report;
- regenerated `SHA256SUMS` after clean packaging preparation.

No migration, dependency, order endpoint or public breaking schema was added.

## 7. Red -> green evidence

Red command:

```bash
.venv/bin/python -m pytest -q tests/unit/test_policy_actionability_density_2026_07_04.py
```

Before production fix:

```text
FAILED test_quality_gate_rejects_statistically_sparse_policy
E assert True is False
1 failed in 3.13s
```

After production fix and completed test module:

```text
4 passed in 2.67s
```

The tests use explicit independent counts/rates, not the production function as their oracle.

## 8. Migration, API, config and compatibility

- Alembic: unchanged; head `0009_candle_receipt_availability`.
- Existing `.env`: compatible. New `AUTO_TRAIN_MIN_POLICY_TRADE_RATE` defaults to `0.01` when absent.
- API: status payload adds `minimum_policy_trade_rate`; existing fields are unchanged.
- Artifacts: current policy metric schema v10 already emits candidates/trades/rate, so no artifact schema bump was necessary.
- Active incumbent: training or gate failure does not deactivate it; lifecycle semantics unchanged.
- Rollout: stop processes, replace tree, optionally add the setting, restart trainer/API/worker.

## 9. Post-check

| Command | Status | Result |
|---|---|---|
| `.venv/bin/python -m pip check` | PASSED | no broken requirements |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `.venv/bin/python -m ruff check .` | PASSED | all checks passed |
| `.venv/bin/python -m pytest -q` | PASSED | 452 passed, 4 skipped, 55 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `.venv/bin/python -m alembic heads` | PASSED | one head: `0009_candle_receipt_availability` |
| production Bybit mutation scan | PASSED | no create/amend/cancel/withdraw implementation |
| `.venv/bin/python manage.py doctor` | FAILED / ENVIRONMENT | default secrets; no PostgreSQL CLI/server |
| integration suite | NOT RUN | no isolated PostgreSQL server/URL |

Final release-tree integrity passed with 183 checked files / 183 manifest entries. ZIP integrity and clean re-extraction are executed after this report is sealed and are reported with the downloadable artifact.

## 10. Not verified

- Real PostgreSQL integration and transaction/lock behavior.
- Live Bybit behavior, rate limits and public API variability.
- User-specific gate reasons, model artifacts, market-data coverage and realized fills/outcomes.
- Economic optimality of 1%; it is a transparent configurable operational floor.
- Profitability, which requires OOS plus paper/shadow forward evidence.

## 11. Residual risks and limitations

- The gate still relies on point estimates of policy performance; a dedicated uncertainty-aware time-block bootstrap/deflated-selection work package remains necessary.
- A genuinely valuable rare-event strategy may require a separately reviewed lower frequency target rather than silently lowering the default.
- Historical orderbook/fills/funding parity and full walk-forward/drift/PBO/DSR remain incomplete.
- Sparse recommendations may also result from data freshness, exact-candle coverage, baseline status, current spread, EV/RR, portfolio risk or min-order constraints; this patch does not mask those fail-closed reasons.

## 12. Rollback

1. Stop API, worker and trainer.
2. Restore the complete 1.9.4 release tree and its matching `SHA256SUMS`.
3. Remove `AUTO_TRAIN_MIN_POLICY_TRADE_RATE` only if it was added and the older release rejects unknown configuration (current settings ignore extras, so removal is optional).
4. Restart processes and run `doctor` plus the available tests.

No database downgrade or artifact mutation is required.

## 13. Recommended next work package

Implement uncertainty-aware policy promotion using horizon-blocked resampling on final-holdout cohort outcomes, with explicit lower confidence bounds and multiple-selection diagnostics. This should be a separate iteration because it changes metric schema, candidate/incumbent comparability and model governance.
