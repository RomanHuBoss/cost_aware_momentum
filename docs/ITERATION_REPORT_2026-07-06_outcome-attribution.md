# Iteration report — mature outcome attribution

Date: 2026-07-06
Release: 1.35.0

## 1. Input archive and source state

- Input: `cost_aware_momentum-1.34.2-universe-hash-timezone.zip`
- SHA-256: `1bb396552d2a764020b92343752beeca415eaf18324bd2a8798e342a2363530a`
- Source version: 1.34.2
- Python requirement: >=3.12
- Alembic revisions: 0001–0016
- Alembic head: `0016_universe_replay_asof`
- Input archive contained one project root and no release-boundary junk.

## 2. Iteration goal and acceptance criteria

Goal:

> After this iteration, the candidate/live attrition report must connect each prospectively
> instrumented signal and initial execution plan to complete-horizon counterfactual outcomes,
> so rare recommendations and repeated losses can be investigated without weakening a gate or
> treating incomplete/early evidence as valid.

Acceptance criteria:

1. Exact instrumented `signal_id`/`plan_id` rows are joined to persisted outcomes.
2. Only full-horizon mature signals enter outcome comparisons.
3. TP/SL/TIMEOUT and ambiguous outcomes are visible by initial plan status, stage and reason.
4. Sized `VALUED` plans expose descriptive counterfactual R; unsized/unavailable plans do not
   receive fabricated R values.
5. Missing/conflicting mature evidence blocks the report.
6. Report metadata states that evidence is not actual execution PnL and not causal.
7. Existing risk, model-quality and activation contracts remain unchanged.

## 3. Sources read and affected data flow

Read before modification:

- `README.md`, `CHANGELOG.md`, `pyproject.toml`;
- `PATCH_1.34.0.md`, `PATCH_1.34.1.md`, `PATCH_1.34.2.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- source specification DOCX extracted read-only from the archive;
- `app/services/attrition.py`, `app/services/outcomes.py`, `app/services/signals.py`;
- `app/db/models.py`, inference worker/report CLI and relevant tests;
- risk/policy/training/lifecycle code to confirm no threshold change was required.

Affected data flow:

```text
hourly/catch-up JobRun.details
  -> exact signal_id / plan_id extraction
  -> bounded read-only PostgreSQL queries
  -> MarketSignal maturity validation
  -> SignalOutcome + PlanOutcome consistency/coverage
  -> status/stage/reason outcome attribution
  -> CLI and daily report JSON
```

## 4. Baseline

Checks were run in a clean isolated environment because the host interpreter lacked project
packages and had an unrelated global dependency conflict.

| Command | Result |
|---|---|
| `python --version` | Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 694 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | one head: `0016_universe_replay_asof` |

Seven PostgreSQL integration tests were skipped because no isolated `TEST_DATABASE_URL` was
available.

## 5. Confirmed gap and evidence

### CONFIRMED GAP — high

Location:

- `app/services/attrition.py::build_candidate_live_attrition_report`
- `app/services/attrition.py::build_attrition_report_from_records`

Actual behavior:

- only inference/training `JobRun` rows were queried;
- report v2 counted skip/status/reason/gate outcomes;
- persisted `MarketSignal`, `SignalOutcome` and `PlanOutcome` were never loaded;
- no mature-outcome coverage or censoring control existed.

Expected behavior:

- reason groups must be linkable to forward outcomes before deciding whether a gate is useful,
  over-restrictive or simply operating in a loss-making regime;
- early resolved TP/SL cannot be compared with unresolved signals before the full horizon;
- missing mature evidence must block conclusions.

Impact:

The prior report could not answer the user's operational question: whether the few actionable
recommendations were predominantly losing and whether rejected/blocked cohorts would have done
better. This prevented evidence-based diagnosis but did not itself prove that a filter caused
losses.

Why tests missed it:

Existing report tests covered denominators, retry deduplication, reason taxonomy and training
promotion outcomes only.

## 6. Plan and actual diff

Production/reporting:

- `app/services/attrition.py`
- `scripts/attrition_report.py`
- `app/__init__.py`
- `pyproject.toml`

Tests:

- `tests/unit/test_candidate_live_attrition_report_2026_07_05.py`

Documentation/release:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.35.0.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- this report
- `SHA256SUMS`

No ORM model, migration, API endpoint, frontend, risk policy, signal selector, feature, label,
artifact or activation code was changed.

## 7. Red → green evidence

On original 1.34.2 code:

```bash
python -m pytest -q tests/unit/test_candidate_live_attrition_report_2026_07_05.py \
  -k 'attributes_full_horizon or blocks_missing_mature'
```

Result:

```text
2 failed
TypeError: build_attrition_report_from_records() got an unexpected keyword argument 'signals'
```

After implementation the same two tests passed. A later point-in-time acceptance test was
intentionally run red and exposed that a `SignalOutcome.resolved_at` after `report.until` was
still counted (`AssertionError: assert 1 == 0`). The implementation now applies the same
cutoff to signal and plan outcomes, and that test passes. Additional green acceptance tests verify:

- early resolved outcomes are excluded until full-horizon maturity;
- outcomes resolved after the historical report cutoff are excluded point-in-time;
- the database report path loads exact instrumented signal/plan outcomes.

## 8. Implementation details and econometric safeguards

- Report schema advanced to `candidate-live-attrition-report-v3`.
- Outcome attribution schema is `candidate-live-counterfactual-attribution-v1`.
- Signals are mature only when `event_time + horizon_hours <= report.until`.
- Persisted evidence is available to the report only when its timezone-aware `resolved_at <= report.until`; later rows are excluded and counted rather than leaked backward.
- Early TP/SL outcomes remain outside group comparisons, preventing differential
  right-censoring.
- Duplicate signals/outcomes, missing mature outcomes, invalid maturity metadata, inconsistent
  signal/plan labels and invalid valuation/R pairs are fail-closed.
- Groups are descriptive and plan-level. Multiple profiles for one signal remain separate plan
  opportunities.
- R summaries include only finite `PlanOutcome.counterfactual_r` from `VALUED` plans.
- `actual_execution_pnl=false` and `causal_claim=false` prevent semantic overstatement.
- Exact IDs are loaded in batches of 5000 to avoid one unbounded SQL `IN` expansion.

## 9. Migration, API, config and compatibility

- Migration: none.
- `.env`: no changes.
- API/frontend: no changes.
- Artifact/model schema: no changes.
- Existing pure report-builder callers that omit all outcome inputs remain supported with
  outcome status `NOT_REQUESTED`.
- Production report path always supplies signal, signal-outcome and plan-outcome collections and
  applies the strict checks.
- Rollback: restore release 1.34.2; report schema returns to v2. Database data is untouched.

## 10. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | 699 passed, 7 skipped, 62 warnings |
| attrition tests | 8 passed |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | one head: `0016_universe_replay_asof` |
| advisory-only static scan | PASSED |
| version consistency | PASSED: 1.35.0 |

No previously green test regressed.

## 11. Not verified

- PostgreSQL integration execution and query plans: no isolated test database.
- `manage.py doctor`: no configured runtime `.env`/PostgreSQL instance.
- `manage.py test --require-integration`: no isolated PostgreSQL URL.
- Production-sized query latency and peak memory.
- Real Bybit forward/shadow outcomes after deployment.
- Actual manual entry/fill PnL, fees and operator latency.

## 12. Residual risks and limitations

- Historical opportunities before prospective instrumentation cannot be reconstructed.
- `NO_TRADE` and blocked plans commonly have `NOT_SIZED`; outcome labels are available, but an
  R value cannot be computed honestly without a sized plan denominator.
- Outcome groups may be dependent by timestamp, symbol and shared signal. Means/medians are not
  significance tests.
- Ambiguous intrabar outcomes remain visible as an explicit count and depend on the existing
  deterministic outcome-resolution policy.
- This release provides the missing diagnostic evidence. It does not establish profitability,
  identify all alleged external-review errors or justify loosening safeguards.

## 13. Recommended next work package

After enough 1.35.0 forward evidence accumulates, add dependence-aware uncertainty for
status/stage/reason comparisons: cluster by `signal_id` and decision-time blocks, control
multiple comparisons, and report confidence intervals for differences without adapting policy
thresholds on the same evaluation window.
