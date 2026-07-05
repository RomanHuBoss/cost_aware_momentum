# Iteration report — policy opportunity path

## 1. Input archive and identification

- Input: `cost_aware_momentum-main.zip`.
- Input SHA-256: `33a5001d29578abfcbf741ac8f655c969c88ef04a35b7c363628f65742c08586`.
- Input version: 1.26.3.
- Python requirement: >=3.12; executed with Python 3.13.5.
- Alembic migrations: 14; single static head `0014_ui_exposure_ledger`.
- Pristine archive counts: 94 production Python files, 81 test Python files, 6 documentation/source files, 215 files total.
- Input ZIP contained no `.env`, `.venv`, cache directories, bytecode or egg-info. Baseline/tool execution generated local caches/egg-info; they are excluded from the release ZIP.

The repository does not contain the prompt-listed `docs/ARCHITECTURE.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md` or `OPERATOR_MANUAL.md`. This was treated as an explicit documentation-layout conflict, not as evidence that their content exists. The available authoritative repository documents were used instead.

## 2. Goal and acceptance criteria

Goal: after this iteration, model-promotion economic inference must be based on every observed hourly decision opportunity, with a real `NO TRADE` hour represented as zero strategy return, confirmed by an independent regression test and fail-closed schema/accounting checks.

Acceptance criteria:

1. No-trade observed hours remain in policy mean and uncertainty paths.
2. Missing market hours are not fabricated.
3. Trade/no-trade/total cohort counts are explicit and arithmetically consistent.
4. All horizon phases are derived from the same unconditional path.
5. Candidate and incumbent malformed evidence is rejected.
6. Previous trade-conditional metric schemas are not accepted for normal promotion.
7. Advisory-only, PostgreSQL-only and existing absolute policy gates remain unchanged.
8. Full available static/unit suite has no regression.

## 3. Sources and affected data flow

Read or inspected:

- `README.md`, `CHANGELOG.md`, `PATCH_1.26.1.md`–`PATCH_1.26.3.md`;
- `pyproject.toml`, `.env.example`;
- `docs/QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, previous iteration reports;
- `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`, especially ML/policy separation, `NO TRADE`, event-driven net backtest and OOS evidence requirements;
- `app/ml/training.py`, `app/ml/lifecycle.py` and related policy/econometric tests;
- Bybit client, activation services, migrations and frontend boundaries by static inspection.

Affected flow:

`final holdout directional rows` → `direction selection per decision_time × symbol` → `policy/overlap filters` → `trade cohorts reindexed to observed decision cohorts` → `mean/phase/bootstrap evidence` → `quality gate candidate/incumbent validation` → `candidate metrics / promotion decision`.

## 4. Baseline

### Host/global environment

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED | unrelated global MoviePy/Pillow conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | `No module named ruff` |
| `python -m pytest -q` | FAILED | collection: 33 errors because global `psycopg` was missing |
| `node --check web/js/app.js` | PASSED | exit 0 |

### Isolated comparable environment

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | 613 passed, 4 skipped, 61 warnings in 13.84 s |
| `node --check web/js/app.js` | PASSED | exit 0 |

## 5. Confirmed defect

### CONFIRMED DEFECT — high severity: selection-conditioned policy inference

- Location: `app/ml/training.py::evaluate_policy_model`.
- Original path: `trades.groupby("decision_time")` directly supplied the policy mean, horizon phases and bootstrap LCB.
- Reproduction: 16 observed hourly decision cohorts, with profitable actionable trades only in the first 8 and `NO TRADE` in the next 8.
- Expected: 16 opportunity cohorts, 8 trade cohorts, 8 no-trade cohorts and unconditional mean R = 0.5.
- Original behavior: only 8 traded cohorts existed in evidence; no-trade hours were absent, so the economic sample was conditional on selection and the implied mean was 1.0.
- Impact: sparse-policy evidence could be overstated; horizon phase completeness and LCB could depend on where trades occurred; candidate promotion could use an economically incorrect denominator.
- Why tests missed it: existing tests checked overlap, trade counts and phase mechanics using samples where all observed cohorts traded. None created observed hours that deliberately became `NO TRADE` after policy selection.

The defect can plausibly contribute to misleading evidence around rare recommendations, but this iteration does not claim it is the sole cause of observed losses or failed daily candidates.

## 6. Plan and actual diff

Production:

- `app/ml/training.py`: observed opportunity index, zero-return no-trade cohorts, new diagnostics and schemas.
- `app/ml/lifecycle.py`: fail-closed candidate/incumbent count and schema validation.
- `app/__init__.py`, `pyproject.toml`: version 1.26.4.

Tests:

- new `tests/unit/test_policy_opportunity_path_2026_07_05.py`;
- lifecycle regression for inconsistent incumbent opportunity counts;
- existing policy/lifecycle fixtures updated to the v17/v3 contract and explicit counts.

Documentation:

- `README.md`, `CHANGELOG.md`, `PATCH_1.26.4.md`;
- `docs/QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`;
- this iteration report.

Migrations/config/API: no changes.

## 7. Red → green evidence

Command:

```text
python -m pytest -q tests/unit/test_policy_opportunity_path_2026_07_05.py
```

Red on original production code:

```text
1 failed in 2.89s
KeyError: 'policy_trade_cohorts'
```

The test's independent assertions require total = 16, trade = 8, no-trade = 8, 8 phases, 2 independent observations per phase, unconditional mean = 0.5 and LCB no greater than that mean.

Green after implementation: **1 passed in 2.97 s**..

## 8. Compatibility

- Alembic migration: none.
- Database schema: unchanged.
- Public HTTP/API schema: unchanged.
- `.env`: unchanged.
- Existing active artifact/runtime: remains runnable.
- Inactive candidate policy metrics: v16/v2 evidence is intentionally incompatible with v17/v3 and must be regenerated by retraining; governed experiment evidence must then be rerun.
- Rollout does not modify signal thresholds, capital, leverage, costs or execution rules.

## 9. Post-check

| Command/check | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| targeted policy/lifecycle suite | PASSED | 34 passed in 4.49 s |
| `python -m pytest -q` | PASSED | 615 passed, 4 skipped, 61 warnings in 12.63 s |
| `node --check web/js/app.js` | PASSED | exit 0 |
| version consistency | PASSED | app/package 1.26.4 |
| Alembic heads | PASSED | one head: `0014_ui_exposure_ledger` |
| release integrity | PASSED | 217 files / 217 manifest entries |
| `python manage.py doctor` | FAILED (environment) | `.env`, non-default secrets, PostgreSQL tools and PostgreSQL server unavailable |
| `python manage.py test --require-integration` | NOT RUN (integration evidence) | no `TEST_DATABASE_URL` or `POSTGRES_ADMIN_URL` |
| final ZIP validation | PASSED | archive test, one root and clean re-extraction |

## 10. Not verified

- PostgreSQL integration/migration upgrade/rollback on a separate database: no test database credentials were available.
- `manage.py doctor` cannot be green without `.env`, PostgreSQL and PostgreSQL command-line tools; exact result is recorded in QA.
- Live/forward economic performance and recommendation frequency.
- Historical orderbook reconstruction, point-in-time funding forecasts, sub-hour event ordering and exact exchange liquidation mechanics.

## 11. Residual risks and limitations

- A zero return for `NO TRADE` is correct for strategy PnL, but low activity still needs separate opportunity-cost and calibration analysis; the new diagnostics expose rather than solve that research question.
- Unit tests use deterministic synthetic data. External validity requires sufficiently long untouched OOS/forward evidence.
- Experiment-family PBO/DSR is prospective and cannot reconstruct undocumented experiments outside the ledger.
- The claimed external counts of 15/4/8 defects were not accompanied by reproducible evidence; this report records only the defect proven in this iteration.

## 12. Rollback

1. Stop trainer/inference processes.
2. Restore the 1.26.3 source release; no database downgrade is required.
3. Keep the currently active artifact unchanged.
4. Do not activate a candidate whose v17/v3 evidence was produced by 1.26.4 under 1.26.3 code; retrain under the code version intended for deployment.
5. Restart services and rerun static/unit checks.

## 13. Recommended next work package

Implement and validate a prospective decomposition of recommendation scarcity using existing attrition evidence: separate model direction confidence, net-cost/RR/EV rejection, overlap blocking, stale/missing market data, portfolio/risk caps and experiment-promotion failure. Do not lower gates before denominators and reason-code coverage are proven complete.
