# QA Report

Release: **1.35.0**

Date: **2026-07-06**
Scope: **full-horizon counterfactual outcome attribution for candidate/live attrition**

## Environment

- Python: 3.13.5 in an isolated virtual environment.
- Project requirement: Python >=3.12.
- Node syntax check: available.
- Separate PostgreSQL integration database: not configured.
- Input archive: `cost_aware_momentum-1.34.2-universe-hash-timezone.zip`.
- Input archive SHA-256: `1bb396552d2a764020b92343752beeca415eaf18324bd2a8798e342a2363530a`.
- Source version: 1.34.2.

The host Python environment was not used as evidence because it lacked project `psycopg` and
Ruff packages and contained an unrelated `moviepy`/Pillow dependency conflict. All baseline
and post checks below used the same clean project virtual environment.

## Baseline before changes

| Check | Result |
|---|---|
| input release structure | PASSED: one project root; no `.env`, caches, bytecode, dumps or model artifacts |
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 694 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |

The seven skipped tests require an isolated PostgreSQL integration database.

## Confirmed gap

`app/services/attrition.py::build_candidate_live_attrition_report` queried only `JobRun`.
`build_attrition_report_from_records` aggregated terminal reason/status counts but accepted no
market-signal, signal-outcome or plan-outcome records. Existing persisted outcome evidence was
therefore absent from the report.

Impact: the operator could see why opportunities were filtered but could not determine whether
an actionable group later lost, whether a blocked group later hit TP, or whether missing outcome
coverage made such a comparison invalid. Severity: **high diagnostic/econometric gap**. It did
not itself prove that any safety gate should be loosened.

Existing tests missed the gap because they asserted only attrition denominators and reason
counts.

## Red evidence

On unchanged 1.34.2 code, the first two new contract tests failed before implementation:

```text
test_report_attributes_full_horizon_outcomes_to_plan_filters
TypeError: build_attrition_report_from_records() got an unexpected keyword argument 'signals'

test_report_blocks_missing_mature_outcome_evidence
TypeError: build_attrition_report_from_records() got an unexpected keyword argument 'signals'
```

Command:

```bash
python -m pytest -q tests/unit/test_candidate_live_attrition_report_2026_07_05.py \
  -k 'attributes_full_horizon or blocks_missing_mature'
```

Result: **2 failed** for the expected missing-contract reason.

A separate point-in-time regression was then introduced after review of the first implementation:

```text
test_report_excludes_outcomes_resolved_after_report_cutoff
AssertionError: assert 1 == 0
```

The red result proved that a `SignalOutcome` resolved after `report.until` was still counted in a
historical cohort. After adding the `resolved_at` availability cutoff, the test passed and both
signal and plan post-cutoff rows were excluded and counted.

## Implemented correction

- Added exact-ID outcome loading in bounded batches.
- Added full-horizon maturity partitioning based on `event_time + horizon_hours`.
- Added point-in-time availability filtering requiring timezone-aware `resolved_at <= report.until`; post-cutoff rows are excluded and counted.
- Added mature TP/SL/TIMEOUT and ambiguity counts.
- Added plan valuation status and valued `counterfactual_r` summaries.
- Added status/stage/primary-reason grouping.
- Added fail-closed mature outcome coverage and cross-record consistency checks.
- Preserved backward compatibility for pure callers that explicitly do not request outcome data;
  production always supplies the complete input triplet.
- Explicitly marked the evidence as counterfactual/descriptive, not actual execution PnL or a
  causal estimate.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 699 passed, 7 skipped, 62 warnings |
| attrition report suite | PASSED: 8 passed |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |
| advisory-only mutation-method scan | PASSED |
| version consistency | PASSED: 1.35.0 in package, application, README and changelog |

## Environment-dependent checks

| Check | Result |
|---|---|
| PostgreSQL integration tests | SKIPPED: 7 tests; `TEST_DATABASE_URL` unavailable |
| actual PostgreSQL batch-query execution/performance | NOT RUN |
| `python manage.py doctor` | NOT RUN: configured `.env` and PostgreSQL runtime unavailable |
| `python manage.py test --require-integration` | NOT RUN: no isolated PostgreSQL integration database |
| real Bybit forward/shadow cycle | NOT RUN |
| actual operator fill PnL attribution | NOT IMPLEMENTED; report is counterfactual only |
| causal/dependence-aware reason-group inference | NOT IMPLEMENTED |

## Release boundary

- Database migration: **none**.
- New `.env` settings: **none**.
- HTTP/frontend schema: **unchanged**.
- Model artifact, feature, label and class schema: **unchanged**.
- Quality, activation, risk and capital thresholds: **unchanged**.
- New dependency: **none**.
- Bybit client remains read-only and advisory-only.

## Residual limitations

- Outcome evidence is prospective and cannot reconstruct pre-instrumentation opportunities.
- `counterfactual_r` exists only for sized `VALUED` plans. The report does not invent an R value
  for `NO_TRADE` or blocked plans that were not sized.
- TP/SL/TIMEOUT comparison is descriptive. It does not control for symbol/time dependence,
  multiple testing, regime mix or operator selection.
- Actual manually executed fills and realized fees/slippage are outside this report.
- No change in this release establishes profitability or justifies weakening a gate.
