# Iteration Report — 2026-07-02 — conditional TIMEOUT economics

## 1. Input archive and source state

- Input: `cost_aware_momentum-main.zip`.
- SHA-256: `9104ab43d0636d8b3aa31cfd7370aeed23009d73b0aa3b604d8ef03fa8b2635b`.
- Source version: `1.8.36`; result version: `1.9.0`.
- Python requirement: `>=3.12`.
- Alembic: revisions `0001`–`0008`, one head `0008_outcome_path_unavailable`.
- Source inventory: 70 production/maintenance Python files including `manage.py`, 50 `test_*.py` modules, 18 Markdown documentation files.

## 2. Iteration goal and acceptance criteria

Goal:

> After this iteration, ML TIMEOUT economics must be estimated only from the training window, remain direction-aware, and be identical across promotion evaluation, research backtest, live signal selection, execution-plan construction and acceptance validation.

Acceptance criteria:

1. Training derives TIMEOUT gross return in stop-risk units from actual labeled outcomes, never from final holdout.
2. LONG and SHORT receive separate robust estimates with a minimum evidence count.
3. Runtime artifacts declare an exact TIMEOUT schema and old artifacts fail closed.
4. Live direction selection uses scenario-specific TIMEOUT economics rather than one global `-0.2%` assumption.
5. Market signal persists the exact used assumption; plan and acceptance reuse it even if `.env` changes.
6. Research/promotion paths use the same estimator; explicit backtest CLI override remains possible and visible.
7. Existing advisory-only, PostgreSQL-only, risk and activation gates remain unchanged.
8. Full static/unit checks remain green and release archive contains no test/build debris or secrets.

## 3. Sources read and affected data flow

Read before edits:

- `README.md`, `CHANGELOG.md`, `PATCH_1.8.36.md`;
- `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`, especially point-in-time validation, TP/SL/TIMEOUT EV and technical-correctness-versus-profitability sections;
- ML training/lifecycle/runtime, signal policy, execution economics, risk math, market-data ingestion, backtest and related tests.

Affected flow:

`confirmed candles → barrier labels with realized gross return and stop distance → purged train/calibration/final holdout → train-only LONG/SHORT TIMEOUT median in R units → immutable artifact schema → runtime directional Prediction → tick-aligned live EV → persisted market signal assumption → execution plan / acceptance / serializer`.

Research flow:

`same artifact + final holdout → model-aware policy evaluation/backtest`; an explicit backtest timeout CLI argument deliberately switches source to `explicit_override`.

## 4. Baseline before edits

The system Python was not a valid project environment: `ruff` and `psycopg` were absent, `pip check` exposed an unrelated global `moviepy/Pillow` conflict, and pytest had 23 import errors. No code defect was inferred from that environment.

A clean external virtualenv with project dev dependencies produced:

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | 425 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0008_outcome_path_unavailable (head)` |
| `python manage.py doctor` | NOT RUN | no operator `.env` / safe PostgreSQL environment |
| `python manage.py test --require-integration` | NOT RUN | no isolated PostgreSQL test DB; user/production DB not used |

## 5. Confirmed defects/gaps

### 5.1 HIGH — fixed global TIMEOUT return corrupts EV semantics

Classification: `CONFIRMED DEFECT`.

Evidence:

- `app/ml/training.py::PolicyEvaluationConfig.timeout_return_rate` defaulted to `-0.002`.
- `evaluate_policy_model` used that single value for every LONG/SHORT holdout row.
- `app/services/signals.py::select_cost_aware_scenario` received one value for both directional predictions.
- `app/services/execution.py` recomputed plan and acceptance EV from the current setting instead of the signal-level assumption.
- `scripts/backtest.py::policy_backtest` used the same fixed value even for a validated artifact.
- The label dataset already contained `realized_gross_return` and `barrier_downside_rate`, so the information needed for an honest training-only estimator existed but was ignored.

Minimal counterexample:

- identical TP/SL/TIMEOUT probabilities for LONG and SHORT;
- LONG TIMEOUT expectation `-0.8R`, SHORT `+0.8R`;
- the old fixed assumption ranked them as a tie and selected LONG by tiebreak;
- the corrected estimator selects SHORT and preserves the corresponding positive realized holdout path.

Impact: financial/econometric and operational. The defect could suppress genuinely positive TIMEOUT-heavy scenarios, approve materially worse ones, choose the wrong direction and make plan economics change after publication when `.env` changed.

Why tests missed it: prior tests only proved that one explicit fixed assumption was reused consistently; they did not challenge the assumption with directionally different observed TIMEOUT outcomes.

### 5.2 HIGH — confirmed residual candle availability defect

Classification: `CONFIRMED DEFECT`, deliberately not fixed in this work package.

`app/services/market_data.py::_candle_values` receives the post-response `now` but stores `available_at=close_time`. A candle fetched hours or days later can therefore appear historically available at its close time. The test named `test_candle_confirmation_uses_api_response_time` correctly verifies the confirmation flag against response time but asserts the incorrect availability timestamp.

Safe correction needs a separate migration/reingestion policy because true receipt timestamps for existing historical rows cannot be reconstructed. This is the recommended next work package.

### 5.3 Documented research limitations

- current-symbol historical universe selection can retain survivorship/listing bias;
- historical order book, fills, exact funding timeline and operator latency are not fully replayed;
- full rolling walk-forward, regime/drift governance, PBO/DSR are not fully implemented;
- no technical check in this iteration proves profitability.

## 6. Plan and actual diff

Production/config:

- `app/ml/training.py`
- `app/ml/lifecycle.py`
- `app/ml/runtime.py`
- `app/services/signals.py`
- `app/services/execution.py`
- `scripts/backtest.py`
- `app/__init__.py`, `pyproject.toml`, `.env.example`

Tests:

- new `tests/unit/test_conditional_timeout_economics_2026_07_02.py`;
- artifact-contract fixtures updated in `test_runtime_auth_config.py`, `test_external_recommendation_review_2026_07_01.py`, `test_model_artifact_recovery.py`, `test_quant_econometric_audit_2026_06_29.py`, `test_quant_integrity_2026_07_02.py`;
- policy schema expectations updated in `test_model_lifecycle.py`, `test_quant_integrity_2026_06_29.py`, `test_quant_policy_integrity_2026_06_30.py`, `test_training_evidence_integrity_2026_07_02.py`.

Documentation/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.9.0.md`;
- `docs/ARCHITECTURE.md`, `CONFIGURATION.md`, `MODEL_CARD.md`, `OPERATOR_MANUAL.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, this report;
- regenerated `SHA256SUMS` after final cleanup.

No ORM model or database schema changed; no migration was added.

## 7. Red → green evidence

Initial command after adding the acceptance tests but before production implementation:

```text
python -m pytest -q tests/unit/test_conditional_timeout_economics_2026_07_02.py
```

RED result:

```text
ImportError: cannot import name 'TIMEOUT_RETURN_SCHEMA_VERSION' from 'app.ml.training'
1 error during collection
```

This was the intended failure: the artifact/economic contract did not exist.

GREEN result after implementation:

```text
7 passed, 36 warnings
```

The seven tests independently verify training medians/counts, live direction selection, artifact rejection, runtime propagation, promotion-policy selection, signal-to-plan immutability/fail-closed validation and model-aware research backtest behavior.

## 8. Migration, API, config and compatibility

- Migration: none.
- Public HTTP/API schema: no breaking field removal or endpoint change.
- `.env`: no new variable. `TIMEOUT_GROSS_RETURN_RATE` remains valid but is baseline/legacy fallback only.
- Artifact contract: intentionally incompatible. `timeout_return_schema_version=training-direction-median-r-v1` is mandatory.
- Policy evidence contract: `decision-open-entry-exit-time-cohort-v10`.
- Existing persisted signals keep their original snapshot assumption; no historical data is rewritten.
- Advisory-only and read-only Bybit boundaries are unchanged.

## 9. Post-check

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | 432 passed, 4 skipped, 55 warnings |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | one head `0008_outcome_path_unavailable` |
| release manifest check | PASSED | executed after cleanup/repack |
| archive integrity / clean re-extraction | PASSED | executed after packaging |

The additional warnings are NumPy/joblib deprecation warnings from artifact serialization tests.

## 10. Not verified

- `python manage.py doctor`: no local operator `.env` and safe PostgreSQL service configuration.
- `python manage.py test --require-integration`: no isolated PostgreSQL test DB.
- Real migration upgrade/restore: no migration was added, and user DB was not touched.
- Bybit network smoke, paper/shadow forward evidence and actual fill performance: not performed.

## 11. Residual risks and limitations

1. The estimator is a robust direction-conditional median, not feature-conditional regression; it is intentionally minimal and must earn promotion through existing gates and forward evidence.
2. Minimum five TIMEOUT rows per direction can block a candidate with class collapse or insufficient evidence; this is fail-closed by design.
3. Current barrier support clipping is deterministic and prevents impossible expected outcomes after tick rounding, but should be monitored in candidate metrics during future refinement.
4. The confirmed candle `available_at` defect remains high priority.
5. No statement of profitability is made.

## 12. Rollback

1. Stop API, worker and trainer.
2. Restore the complete 1.8.36 release tree and its matching manifest.
3. Do not attempt to load a 1.9.0 artifact in 1.8.36 or vice versa.
4. Restore the previously registered 1.8.36 artifact path/hash if it still exists and passed that release's gates.
5. No database downgrade is required because 1.9.0 adds no migration and does not rewrite stored signals.
6. Restart and run the release's normal checks.

## 13. Recommended next work package

Correct candle availability semantics end-to-end:

- set new candle `available_at` to actual post-response receipt time;
- replace the misleading test assertion;
- define an irreversible, fail-closed migration or controlled reingestion policy for legacy rows;
- prove point-in-time replay cannot use a late-fetched candle before its true availability;
- update compliance/traceability and run PostgreSQL integration tests on a disposable database.
