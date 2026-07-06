# QA Report

Release: **1.28.0**

Date: **2026-07-06**  
Scope: **risk-budgeted experiment portfolio accounting**

## Environment

- Python: 3.13.5 in isolated virtual environment `/mnt/data/cam_venv`.
- Project requirement: Python >=3.12.
- Node syntax check available.
- Separate PostgreSQL integration database: not configured.
- Host/global Python was unsuitable: `ruff`/`psycopg` were absent and global `pip check` had an unrelated MoviePy/Pillow conflict.

## Baseline before changes

| Check | Result |
|---|---|
| input ZIP SHA-256 | `2fac93ab04fb012b7d29027c33e3931d6b54ef5a211963aa600224df654d2f70` |
| source version | 1.27.0 |
| source inventory | 228 files; 94 production Python, 84 test Python, 11 docs; 14 migration revisions; head `0014_ui_exposure_ledger` |
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED in isolated venv |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 636 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |

## Confirmed defect and red evidence

`scripts/backtest.py::_simulate_capital_sleeves_evidence` assigned each simultaneous trade the same notional share of a fixed horizon sleeve. `app/risk/math.py::calculate_position_plan` instead derives notional from `risk_budget / stress_downside_rate` and applies portfolio-risk and margin caps. Formal Sharpe/DSR/PBO/cost-stress evidence therefore measured a different portfolio than the execution-plan contract.

Independent counterexample:

- trade A: downside 1%, realized return +2%;
- trade B: downside 10%, realized return -5%;
- old equal-notional result: `(2% - 5%) / 2 = -1.5%`;
- live-style equal 0.35% risk budgets: `0.0035/0.01×0.02 + 0.0035/0.10×(-0.05) = +0.525%`.

Original red command:

```text
python -m pytest -q tests/unit/test_risk_budgeted_experiment_accounting_2026_07_06.py
```

Before production implementation: collection failed because `_simulate_risk_budgeted_portfolio_evidence` did not exist. After implementation and extensions: **4 passed** in that module.

## Added/extended regression coverage

- Equal-risk sizing reproduces independent arithmetic and exposes the equal-notional sign reversal.
- Overlapping cohorts are scaled to the remaining aggregate open-risk budget.
- Margin reserve and leverage proportionally limit a simultaneous cohort.
- Hourly period returns reconcile exactly to terminal risk-budgeted equity.
- Existing backtest fee, open-gap, stop-reserve, MTM and cost-stress tests were updated to assert portfolio PnL after risk sizing while retaining independent trade-level or fee formulas.
- Promotion rejects evidence after `risk_rate`, aggregate-risk or margin-reserve policy changes.
- Legacy cost-stress/policy-binding/period-return contracts remain fail-closed.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 641 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| application/package version consistency | PASSED: 1.28.0 |
| Alembic heads | PASSED: one head, `0014_ui_exposure_ledger` |
| release manifest | PASSED after regeneration |
| clean ZIP/re-extraction | PASSED: one root directory, archive test and forbidden-artifact scan clean |

## Environment-dependent checks

| Check | Result |
|---|---|
| `python manage.py doctor` | FAILED preflight: project-local managed virtualenv is absent; `.env`/PostgreSQL runtime checks were not reached in the isolated external venv workflow |
| `python manage.py test --require-integration` | FAILED preflight for the same managed-virtualenv requirement; separate PostgreSQL integration tests were not executed |

## Warnings

62 warnings are existing Joblib/NumPy and pandas timedelta deprecations. No new warning category was introduced.

## Release boundary

- Database migration: none.
- Public HTTP request/response schema: unchanged.
- `.env` variables: unchanged.
- Model feature/label/runtime artifact schemas: unchanged.
- Signal direction, entry geometry, TP/SL and actionability thresholds: unchanged.
- Experiment return schema: v3 → risk-budgeted v4.
- Cost-stress schema: v1 → risk-budgeted v2.
- Promotion policy binding: v1 → v2 with risk/max-open-risk/margin-reserve fields.
- Active artifacts remain runnable; stale inactive candidates and experiment-family evidence require regeneration for normal activation.
