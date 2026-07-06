# Iteration report — risk-budgeted experiment portfolio accounting

## 1. Input and source state

- Input archive: `cost_aware_momentum-main.zip`.
- Input SHA-256: `2fac93ab04fb012b7d29027c33e3931d6b54ef5a211963aa600224df654d2f70`.
- Source release: 1.27.0.
- Target release: 1.28.0.
- Python requirement: >=3.12; checks executed with Python 3.13.5 in `/mnt/data/cam_venv`.
- Database revisions: 14; single Alembic head `0014_ui_exposure_ledger`.
- Source inventory: 228 files; 94 production Python, 84 test Python, 11 documentation files.

## 2. Iteration objective and acceptance criteria

Objective:

> After this iteration, formal experiment-selection and cost-stress capital paths must use a deterministic risk-budgeted allocation aligned with the production execution-plan sizing invariants, confirmed by independent arithmetic, cap tests and a green full suite.

Acceptance criteria:

1. Position weight is derived from per-trade stress risk, not equal notional.
2. Absolute open-risk reservation survives until modeled exit and constrains overlap.
3. Simultaneous trades are scaled proportionally without inventing operator order.
4. Aggregate risk, leverage and margin reserve are enforced.
5. Nominal and ×1.5/×2 stress paths share the same allocation semantics and reconcile hourly MTM to terminal equity.
6. Deployment-policy binding includes all sizing parameters.
7. Legacy equal-notional evidence cannot authorize normal activation.
8. Full static/unit suite remains green; advisory-only and PostgreSQL-only boundaries remain unchanged.

## 3. Sources read and affected data flow

Read before the change:

- `README.md`, `CHANGELOG.md`, `PATCH_1.27.0.md`, `PATCH_1.26.7.md`, `PATCH_1.26.6.md`;
- `pyproject.toml`, `.env.example`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- recent iteration reports for experiment MTM, cost stress, policy binding and drift;
- `app/risk/math.py`, `app/risk/policy.py`, `app/services/execution.py`;
- `app/ml/training.py`, `app/ml/lifecycle.py`, `app/research/overfitting.py`;
- `app/services/model_promotion.py`, `app/services/experiment_ledger.py`;
- `scripts/backtest.py` and relevant unit tests.

Relevant flow before the fix:

`final-holdout scenario rows → policy direction/actionability → single-active-symbol filter → equal-notional horizon sleeves → hourly MTM period returns → cost stress / Sharpe / DSR / PBO → experiment ledger → model promotion`.

Production flow:

`signal → capital profile/account state → risk_budget / stress_downside_rate → remaining portfolio risk + margin/depth caps → execution plan`.

Flow after the fix:

`final-holdout scenario rows → policy direction/actionability → single-active-symbol filter → equal desired stress-risk cohort → remaining aggregate-risk and margin proportional scale → hourly MTM period returns → cost stress / Sharpe / DSR / PBO → risk-policy-bound experiment ledger → model promotion`.

## 4. Baseline

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements in isolated venv |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no syntax errors |
| `python -m ruff check .` | PASSED | no findings |
| `python -m pytest -q` | PASSED | 636 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |
| `python manage.py doctor` | FAILED preflight | project-local managed virtualenv absent |
| `python manage.py test --require-integration` | FAILED preflight | project-local managed virtualenv absent; PostgreSQL integration not executed |

## 5. Confirmed defect

### CONFIRMED DEFECT — experiment/live portfolio-weight mismatch

Severity: **critical econometric / high operational**.

Files/functions:

- `scripts/backtest.py::_simulate_capital_sleeves_evidence`;
- `scripts/backtest.py::policy_backtest`;
- production comparison: `app/risk/math.py::calculate_position_plan`, `app/services/execution.py::create_execution_plan`.

Actual behavior:

- each hourly cohort received one horizon sleeve;
- sleeve capital was divided equally by number of trades;
- `stress_downside_rate`, `DEFAULT_RISK_RATE`, `MAX_TOTAL_OPEN_RISK_RATE` and `MARGIN_RESERVE_RATE` did not affect portfolio weights;
- experiment policy binding omitted those sizing parameters.

Expected behavior:

- desired notional must be proportional to `risk_budget / stress_downside_rate`;
- active risk is reserved until exit;
- new entries cannot exceed aggregate risk or margin capacity;
- evidence for a different sizing policy must not authorize deployment.

Minimal counterexample:

| Trade | Stress downside | Realized return | Equal-notional contribution | Equal 0.35% risk contribution |
|---|---:|---:|---:|---:|
| A | 1% | +2% | +1.0% | +0.700% |
| B | 10% | -5% | -2.5% | -0.175% |
| Portfolio | — | — | **-1.5%** | **+0.525%** |

Impact:

- can reverse terminal-return sign and experiment ranking;
- changes drawdown, Sharpe, DSR, PBO and cost-stress promotion evidence;
- can promote an artifact based on portfolio weights not used by execution plans;
- does not by itself prove the cause of the user's live losses, because production outcomes and operator decisions are not included in the archive.

Why existing tests missed it:

Existing tests validated sleeve compounding, observed-period support, intrahorizon MTM and cost reconciliation under the sleeve contract. They did not compare portfolio allocation to the independent production sizing equation.

## 6. Plan and actual diff

Production/research:

- `scripts/backtest.py`: added risk-budgeted portfolio replay; switched nominal, reserve and stress paths; added allocation diagnostics.
- `app/ml/training.py`: carried risk-policy fields in `PolicyEvaluationConfig`.
- `app/ml/lifecycle.py`: persisted risk-policy fields into candidate promotion binding.
- `app/services/model_promotion.py`: policy-binding v2 and risk-policy mismatch validation.
- `app/research/overfitting.py`: period-return v4 and cost-stress v2 schemas.

Tests:

- new `tests/unit/test_risk_budgeted_experiment_accounting_2026_07_06.py`;
- extended policy-binding, backtest economics, MTM/cost-stress, open-gap, stop-reserve and activation fixtures/tests.

Docs/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.28.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this iteration report;
- `pyproject.toml`, `app/__init__.py`, regenerated `SHA256SUMS`.

Migration/API/config:

- no migration;
- no HTTP contract change;
- no new `.env` variable;
- existing risk variables now become part of immutable experiment-policy evidence.

## 7. Red → green evidence

Red command:

```text
python -m pytest -q tests/unit/test_risk_budgeted_experiment_accounting_2026_07_06.py
```

Red result:

```text
ImportError: cannot import name '_simulate_risk_budgeted_portfolio_evidence' from 'scripts.backtest'
```

Green targeted result after implementation and test extension:

```text
4 passed
```

Additional combined accounting/promotion-binding targeted run:

```text
9 passed
```

Independent oracle:

The sign-reversal expected values are calculated directly from the sizing equation and input rates, not from the new helper.

## 8. Compatibility and rollback

- DB migration: none.
- Active model/runtime compatibility: preserved.
- Old inactive candidate binding v1: intentionally rejected for normal activation; retrain to produce binding v2.
- Old experiment-family path v3/cost-stress v1: intentionally rejected; rerun preregistered backtests.
- Emergency rollback behavior remains explicit/reasoned/audited and unchanged.

Rollback procedure:

1. Restore release 1.27.0 source tree and its `SHA256SUMS`.
2. Do not copy 1.28.0 `SUCCEEDED` experiment events into a 1.27.0 environment as equivalent evidence.
3. No database downgrade is required.
4. Existing active artifact may remain active; promotion of new candidates should stay disabled until evidence schemas match the running release.

## 9. Post-change checks

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no syntax errors |
| `python -m ruff check .` | PASSED | no findings |
| `python -m pytest -q` | PASSED | 641 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |
| Alembic head inspection | PASSED | one head, `0014_ui_exposure_ledger` |
| version consistency | PASSED | 1.28.0 in package/application sources |
| release integrity | PASSED | regenerated manifest; forbidden artifacts absent |
| ZIP test/re-extraction | PASSED | one project root; manifest and structure verified |

## 10. Not verified

- PostgreSQL integration/concurrency tests: no separate configured test DB and managed project-local runtime.
- Exact historical minQty/minNotional, notional caps, risk tiers, orderbook depth, partial fills and operator latency/order.
- Profile-specific forward capital paths and actual accepted/rejected recommendation outcomes.
- Profitability, adequate signal frequency and causal reason for observed losses.

## 11. Residual risks and limitations

- Simultaneous cohort allocation is proportional because historical manual ordering is unavailable.
- Research margin capacity approximates available margin from current simulated equity; it does not reconstruct account-level external positions.
- `capital_sleeves` remains as a compatibility output field representing configured horizon, but portfolio PnL no longer uses sleeve allocation.
- A model may still fail economically due to probability calibration, regime drift, selection behavior, unmodeled execution friction or genuinely absent edge.

## 12. Recommended next work package

Use prospective `candidate-live-attrition-report-v2`, verified UI exposure/decisions and mature outcomes to build a profile-aware forward attribution report that separates:

- model-quality/policy rejection;
- risk/margin/liquidity execution-plan blocking;
- operator selection;
- realized post-exposure outcomes.

Do not lower `MIN_NET_EV_R`, `MIN_NET_RR` or quality gates before that evidence is available.
