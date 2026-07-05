# Iteration report — hourly mark-to-market experiment return path

Date: 2026-07-05  
Release: 1.26.6

## 1. Input archive and baseline identity

- Input: `cost_aware_momentum-main.zip`
- SHA-256: `6a7b5bb89053eb519c3afc023a6e3c3d526221e5261da48070b8f9a3a72f7357`
- Initial version: 1.26.5
- Python requirement: >=3.12
- Alembic head: `0014_ui_exposure_ledger`
- Initial tree: one root directory, 221 files; no `.env`, credentials, virtual environment, caches, bytecode, build/dist or model artifacts in the input ZIP.
- The input contained a valid but release-specific `SHA256SUMS`; it is regenerated for 1.26.6.

The repository did not contain the master-prompt example documents `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/CONFIGURATION.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md` or `docs/MODEL_CARD.md`. Their absence was treated as repository fact, not silently replaced by invented files. Available sources included `README.md`, `CHANGELOG.md`, `PATCH_1.26.2.md` through `PATCH_1.26.5.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, prior iteration reports and the embedded source DOCX specification.

## 2. Iteration goal and acceptance criteria

Goal:

> After this iteration, experiment-selection capital returns must reflect every observed hourly mark-to-market change from decision through effective exit, while reconciling exactly to terminal trade/sleeve return and remaining fail-closed when path evidence is incomplete.

Acceptance criteria:

1. A profitable terminal trade with a material interim loss produces the corresponding interim portfolio drawdown.
2. Every research path is hourly, chronological, complete from decision to effective exit and finite.
3. Terminal gross return and signed funding reconcile to the effective realized outcome.
4. Entry fee and conservative slippage are recognized at decision time; terminal exit fee is recognized at exit.
5. Missing or malformed MTM evidence blocks experiment evidence generation.
6. Exit-realized v2 experiment evidence cannot pass the v3 ledger contract.
7. Model features, ex-ante directional ranking, risk thresholds, active artifacts, DB/API/env contracts and advisory-only boundary remain unchanged.
8. The full available suite remains green.

## 3. Read sources and affected data flow

Read/reviewed:

- `README.md`, `CHANGELOG.md`, `pyproject.toml`, `.env.example`;
- `PATCH_1.26.2.md`–`PATCH_1.26.5.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- embedded `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`, especially event-driven backtest, portfolio drawdown, PBO/DSR and intrahorizon MTM requirements;
- `app/ml/mtm.py`, `app/ml/training.py`, `app/ml/funding.py`;
- `scripts/backtest.py`;
- experiment ledger, overfitting and promotion services;
- related unit tests.

Affected flow:

`hourly Bybit mark OHLC + funding settlements` → `make_barrier_dataset` → `cumulative directional gross/funding MTM metadata` → `temporal split metadata` → `policy_backtest` → `cumulative net path` → `horizon capital sleeves` → `experiment period_returns` → `ledger validation` → `Sharpe/HAC/DSR/PBO/moving-block governance` → `normal promotion gate`.

Future mark/funding evidence remains realized-only metadata. It does not enter model fitting, probability prediction, expected EV or LONG/SHORT ranking.

## 4. Baseline before changes

### Host/global environment

- `python --version`: Python 3.13.5 — PASSED.
- `python -m compileall -q app scripts tests manage.py` — PASSED.
- `node --check web/js/app.js` — PASSED.
- `python -m pip check` — FAILED because of an unrelated host Pillow/MoviePy conflict.
- `python -m ruff check .` — UNAVAILABLE (`ruff` absent).
- `python -m pytest -q` — FAILED during collection with 34 import errors (`psycopg` absent).

These host results were not used as the comparable baseline.

### Isolated project environment

Virtual environment: `/mnt/data/cam_1265_venv`

| Command | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 618 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED |

## 5. Confirmed defect

### CONFIRMED DEFECT — exit-only capital recognition

- Severity: **high**.
- Files/functions: `scripts/backtest.py::_simulate_capital_sleeves_evidence`, called by `policy_backtest` and persisted to the experiment ledger.
- Actual behavior: each trade contributed zero during its holding interval and its complete return only at `exit_time`.
- Expected behavior: portfolio equity and drawdown must follow observed hourly mark/funding changes, then reconcile to terminal return.
- Minimal reproduction: one two-hour trade with cumulative returns `0%, -20%, +1%`, horizon `H=2`, one 50% sleeve.
  - Before: period returns `[0.0, 0.0, 0.005]`, max drawdown `0.0`.
  - Expected: `[0.0, -0.10, 0.105/0.90]`, max drawdown `-0.10`, terminal portfolio return still `+0.005`.
- Impact: understated drawdown and changed variance, serial dependence, effective sample size, Sharpe, DSR, PBO and moving-block evidence used for model-selection governance. Because the system is advisory-only and activation is gated, this is classified high rather than an asserted realized-trading critical loss.
- Why tests missed it: existing tests checked terminal sleeve reconciliation and inclusion/exclusion of calendar hours, but did not include an adverse intermediate MTM path followed by recovery.

The user-reported external counts of “15 + 8 critical and 4 medium” could not be verified because no module names, cases or reports were provided. No arbitrary defect count was manufactured.

## 6. Change plan and actual diff

### Production

- `app/ml/mtm.py`
  - adds `INTRAHORIZON_MTM_PATH_SCHEMA_VERSION`;
  - builds cumulative hourly mark-close gross/funding paths through effective exit.
- `app/ml/training.py`
  - preserves MTM metadata through splits;
  - validates completeness, chronology, hourly support and terminal reconciliation;
  - records path schema in dataset metadata.
- `scripts/backtest.py`
  - converts gross/funding paths to cumulative net paths;
  - recognizes entry fee and conservative slippage at decision, terminal exit fee/outcome at exit;
  - aggregates incremental hourly PnL in capital sleeves;
  - fails closed when experiment MTM evidence is missing.
- `app/research/overfitting.py`
  - raises period-return schema from exit-realized v2 to hourly-MTM v3.
- `app/__init__.py`, `pyproject.toml`
  - version 1.26.6.

### Tests

- `tests/unit/test_experiment_overfitting_governance_2026_07_05.py`
- `tests/unit/test_experiment_observed_period_path_2026_07_05.py`
- `tests/unit/test_intrahorizon_liquidation_mtm_2026_07_05.py`
- `tests/unit/test_policy_metadata_split_contract_2026_07_05.py`

### Documentation/release

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.26.6.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- this iteration report
- regenerated `SHA256SUMS`

### Migration/config/API

- Alembic migration: none.
- Public HTTP API: unchanged.
- `.env`: unchanged.
- Model feature, label and runtime artifact schemas: unchanged.
- Risk, EV/RR and model-quality thresholds: unchanged.

## 7. Red → green evidence

Primary regression:

```text
python -m pytest -q tests/unit/test_experiment_overfitting_governance_2026_07_05.py::test_capital_sleeve_evidence_marks_intrahorizon_drawdown_before_profitable_exit
```

- Red: failed; obtained `[0.0, 0.0, 0.005]` instead of `[0.0, -0.10, 0.116666…]`.
- Green: passed after incremental MTM capital accounting.

Additional coverage:

- `test_experiment_net_path_recognizes_entry_costs_before_exit`;
- `test_experiment_evidence_fails_closed_without_hourly_mark_to_market_path`;
- `test_exit_realized_v2_experiment_return_schema_is_rejected`;
- extended dataset/split tests for schema, hourly path preservation and liquidation terminal reconciliation.

## 8. Compatibility and rollback risk

- Active artifacts remain runtime-compatible because model feature/label/runtime schema constants were not changed.
- Existing successful experiment trials under v2 are intentionally incompatible with v3 and require governed reruns before normal promotion.
- Backtest deployment-policy binding now names `horizon_sleeves_hourly_mark_to_market_single_active_symbol_v3`, preventing reuse of exit-only evidence for a different accounting contract.
- No live order placement/change/cancel code was introduced.

## 9. Post-change checks

| Command/check | Result |
|---|---|
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 622 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED: single head `0014_ui_exposure_ledger` |
| version consistency | PASSED: package/app 1.26.6 |
| static order-mutation scan | PASSED: no create/amend/cancel/order POST paths added |

Release-tree manifest and ZIP verification are recorded in `docs/QA_REPORT.md` after packaging.

## 10. Checks not completed

- `python manage.py doctor` — FAILED in the sandbox: `.env` absent, default secrets unresolved, PostgreSQL tools absent and server unreachable. This is an environment failure, not hidden as a pass.
- `python manage.py test --require-integration` — FAILED before test execution because neither `POSTGRES_ADMIN_URL` nor `TEST_DATABASE_URL` is configured.
- No live Bybit, forward paper/shadow, operator-latency or profitability validation was performed.

## 11. Residual risks and limitations

- Hourly mark close cannot recover sub-hour barrier/liquidation ordering.
- Exact historical bid/ask, depth, queue position, partial fills and operator latency remain unavailable for old periods.
- Historical exchange risk tiers/MMR, liquidation fees, cross/portfolio margin and ADL are not reconstructed.
- The work package corrects experiment-selection capital evidence. `evaluate_policy_model` retains its existing separate return-in-R/cohort methodology; aligning its drawdown uncertainty with full MTM is a distinct future package.
- Technical correctness does not establish positive edge or sufficient recommendation frequency. No gate was loosened.

## 12. Rollback procedure

1. Stop API, worker and trainer processes.
2. Restore the 1.26.5 source tree or previous release ZIP.
3. No database downgrade is needed.
4. Do not reuse v3 trials with 1.26.5; schema validation will differ.
5. Be aware that rollback restores the exit-only drawdown defect. Keep normal experiment-based promotion disabled until returning to 1.26.6 or later.

## 13. Recommended next work package

Align final-holdout policy-quality drawdown/uncertainty in `evaluate_policy_model` with the same cumulative MTM path in stop-risk (`R`) units, with independent red → green tests and no threshold weakening. This should be handled separately because it changes candidate/incumbent quality-gate semantics rather than only experiment-family evidence.
