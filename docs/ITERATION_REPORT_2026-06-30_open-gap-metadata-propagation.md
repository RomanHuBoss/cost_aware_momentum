# Iteration report — open-gap metadata propagation

Date: 2026-06-30
Target version: 1.8.13
Scope: ML temporal metadata, holdout/backtest semantics, promotion-schema isolation

## 1. Input archive and baseline identity

- Input: `cost_aware_momentum-main(2).zip`
- Input SHA-256: `66485975761a2741c94c94d5043844a2d4d75be5ca5c14a3faa2ddc6858c6ea5`
- Source version: `1.8.12`
- Python requirement: `>=3.12`
- Test environment: Python 3.13.5 in an isolated external virtual environment
- Alembic head: `0006_manual_trade_remaining_risk`
- Input release integrity: 147 files checked, 147 manifest entries
- Input tree contained no `.env`, virtual environment, Python caches, test caches, build directory, database dump or model artifact.

## 2. Goal and acceptance criteria

> After this iteration, opening-gap timing must survive the complete labeled-dataset → chronological split → policy/backtest → promotion-gate path, and metrics computed with the corrected contract must not be compared with affected v3 evidence.

Acceptance criteria:

1. `chronological_split()` requires `exit_at_open` and preserves it in final-holdout metadata.
2. A known opening-gap row retains `exit_time == decision_time` after split and validation.
3. Missing or non-boolean `exit_at_open` fails closed before policy/backtest metrics are computed.
4. Policy metrics publish a new schema version.
5. The promotion gate accepts v4 and rejects affected v3 metrics.
6. Existing tests remain green and advisory-only/PostgreSQL-only boundaries are unchanged.
7. Release tree is clean and its manifest is regenerated.

## 3. Sources and data flow reviewed

Reviewed: `README.md`, `CHANGELOG.md`, patches 1.8.10–1.8.12, `pyproject.toml`, `.env.example`, architecture, QA, compliance, traceability, model card, configuration, security, incident runbook, operator manual, risk/cost math, execution-plan service, signal publication, labels, training/lifecycle/runtime, counterfactual outcomes, backtest, API serializers, frontend and unit/integration tests.

Affected flow:

`confirmed hourly OHLC → triple_barrier_outcome → make_barrier_dataset(exit_at_open) → chronological_split(test_meta) → validate_policy_evaluation_metadata(exit_time) → evaluate_policy_model/policy_backtest → policy metrics → lifecycle quality gate`

## 4. Baseline before changes

| Check | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 272 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| release integrity | PASSED — 147/147 |
| `python manage.py test --require-integration` | NOT RUN — no isolated PostgreSQL test database |
| `python manage.py doctor` | NOT RUN — no safe runtime `.env`/PostgreSQL configuration |

The four skipped tests explicitly require `TEST_DATABASE_URL`. The warnings are NumPy/joblib deprecation warnings in runtime artifact tests.

## 5. Confirmed defects

### 5.1 HIGH — opening-gap timing dropped by chronological split

- File/function: `app/ml/training.py::chronological_split`.
- Source dataset correctly contained `exit_at_open` from `make_barrier_dataset`.
- `meta_columns` omitted it, so normal training output lost the flag before holdout evaluation.
- `validate_policy_evaluation_metadata` consequently reconstructed the exit at candle close.
- Impact: distorted event ordering, drawdown timing, concurrent-trade periods and any time-dependent settlement/evaluation using modeled exit time; promotion evidence could change.
- Existing coverage missed the defect because the 1.8.12 test built `DatasetSplit.test_meta` manually with the field already present.

### 5.2 HIGH — missing metadata silently changed semantics

- File/function: `app/ml/training.py::validate_policy_evaluation_metadata`.
- Missing `exit_at_open` was converted to all-`False` instead of rejected.
- Impact: malformed or legacy metadata appeared valid and silently applied close-time semantics.
- This fallback masked defect 5.1 and violated the documented fail-closed v3 contract.

### 5.3 HIGH — corrected and affected metrics shared one schema identifier

- Files/functions: `app/ml/training.py::POLICY_METRIC_SCHEMA`, `app/ml/lifecycle.py::evaluate_quality_gate`.
- Affected 1.8.12 metrics and corrected metrics would both advertise v3.
- Impact: candidate/incumbent comparison and auto-activation could treat temporally incompatible evidence as homogeneous.
- Resolution requires schema isolation, not only a local column fix.

The anonymous expert/Claude defect totals were not treated as evidence and could not be independently mapped to files. No unsupported count was claimed.

## 6. Change plan and actual diff

### Production

- `app/ml/training.py`
  - requires boolean `exit_at_open` in split input;
  - preserves it in test metadata;
  - rejects missing field in policy validation;
  - publishes policy schema `exit-time-open-gap-propagated-horizon-sleeves-v4`.
- `app/__init__.py`, `pyproject.toml`
  - version 1.8.13.

### Tests

- `tests/unit/test_barrier_open_gap_integrity.py`
  - full split propagation regression;
  - split missing-field rejection;
  - direct policy metadata rejection.
- `tests/unit/test_model_lifecycle.py`
  - v4 acceptance and v3 rejection.
- Existing synthetic policy/backtest fixtures were updated to state `exit_at_open=False` explicitly rather than relying on the removed fallback.

### Documentation/release

- `README.md`, `CHANGELOG.md`, `PATCH_1.8.13.md`;
- `docs/ARCHITECTURE.md`, `docs/MODEL_CARD.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/QA_REPORT.md`;
- this report and regenerated `SHA256SUMS`.

No migration, API, frontend or `.env` change.

## 7. Red → green evidence

| Regression | Red on original behavior | Green after fix |
|---|---|---|
| `test_chronological_split_preserves_open_gap_exit_metadata` | `exit_at_open` absent from `test_meta` | passed |
| `test_chronological_split_rejects_missing_open_gap_exit_metadata` | expected `ValueError`, none raised | passed |
| `test_policy_metadata_rejects_missing_open_gap_exit_contract` | expected `ValueError`, none raised | passed |
| `test_quality_gate_requires_open_gap_propagation_metric_schema` | v4 candidate rejected as invalid schema | passed; v3 rejected |

The tests use independently specified timestamps and expected contracts; none use the tested function as its own oracle.

## 8. Migration, API and configuration compatibility

- Alembic: unchanged, single head `0006_manual_trade_remaining_risk`.
- PostgreSQL schema: unchanged.
- `.env`: unchanged.
- HTTP/API/UI and Bybit read-only client: unchanged.
- Research compatibility: manually assembled `DatasetSplit.test_meta` must now provide boolean `exit_at_open`.
- Model evidence: recompute holdout/backtest metrics; v3 is intentionally incompatible with v4.

## 9. Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 276 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | `0006_manual_trade_remaining_risk` |
| release integrity | PASSED — 149 files checked, 149 manifest entries |
| archive test/re-extraction | PASSED during final packaging; one root directory, no forbidden artifacts |

## 10. Not verified

- PostgreSQL integration tests, clean-database migration upgrade/downgrade and `manage.py doctor`: no isolated PostgreSQL/runtime configuration.
- Economic profitability, live fill quality and forward/shadow performance: no valid forward evidence was supplied.
- The anonymous third-party error counts: no findings, files or reproduction steps were supplied.

## 11. Residual risks and limitations

- Existing v3 policy/backtest reports must not be compared to v4 without recomputation.
- Counterfactual signal outcomes still have the documented availability-time limitation between hourly event time and actual publication; this iteration did not invent tick-level precision.
- Historical orderbook impact, no-fill/partial-fill simulation, multi-fold walk-forward, drift auto-rollback and full execution latency remain outside the current implementation.
- PostgreSQL-specific locking, migrations and idempotency were not re-executed in this environment.

## 12. Rollback

1. Stop trainer/API/worker if running.
2. Restore the 1.8.12 source tree and its original `SHA256SUMS`.
3. Do not reuse v4 policy metrics with 1.8.12; restore/recompute a homogeneous evidence set.
4. No database downgrade is needed.

Rollback reintroduces the documented open-gap metadata loss and is not recommended for model promotion.

## 13. Recommended next work package

Independently audit funding economics against point-in-time settlement-rate history across live planning, holdout policy, counterfactual valuation and backtest. The next iteration should separate conservative pre-trade funding assumptions from realized settlement cash flows and must not approximate unavailable historical rates as known.
