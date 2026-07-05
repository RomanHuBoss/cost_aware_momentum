# Iteration Report — exact experiment-to-deployment policy binding

Date: 2026-07-05
Release: 1.26.3

## 1. Input archive and baseline identity

- Input archive: `cost_aware_momentum-main(2).zip`
- Input SHA-256: `b7e007e499f04d8c3116d598466bea3f3c97f77b52e84ac2912c5240601635ea`
- Input size: 647,670 bytes
- Source version: 1.26.2
- Python requirement: >=3.12
- Source inventory excluding caches/build artifacts:
  - production Python files: 94
  - test Python files: 80
  - documentation files under `docs/`: 5
  - Alembic migrations: 14
- Source Alembic head: `0014_ui_exposure_ledger`

The archive was unpacked into a clean working directory. No production `.env`, credentials, database dump or model artifact was used.

## 2. Iteration objective and acceptance criteria

Objective:

> After this iteration, normal model promotion must prove that the selected preregistered experiment was evaluated under the same deployment-relevant trading policy that the candidate and production runtime will use.

Acceptance criteria:

1. A `READY` trial with exact model SHA/version/horizon but different slippage or EV threshold is rejected.
2. Exact policy match remains eligible when all existing experiment evidence passes.
3. The candidate persists one immutable policy-binding contract at training time.
4. Fresh training activation, deferred trainer promotion and registry activation use the same contract.
5. Changing deployment settings after backtesting invalidates stale promotion evidence.
6. Legacy inactive candidates/gates without policy binding fail closed.
7. Quality gate, artifact validation, active-version compare-and-swap, audit and outbox guarantees remain unchanged.
8. Full unit/static suite remains green and release documentation is synchronized.

## 3. Sources read and affected data flow

Reviewed before modification:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.26.2.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/QA_REPORT.md`
- `docs/ITERATION_REPORT_2026-07-05_deferred-model-promotion.md`
- `pyproject.toml`
- `.env.example`
- `app/ml/lifecycle.py`
- `app/ml/training.py`
- `app/ml/runtime.py`
- `app/services/model_promotion.py`
- `app/services/model_activation.py`
- `app/services/experiment_ledger.py`
- `app/research/preregistration.py`
- `app/workers/trainer.py`
- `scripts/backtest.py`
- `scripts/train.py`
- related activation, experiment, attrition and deferred-promotion tests

Affected flow:

```text
Settings + training PolicyEvaluationConfig
  -> build_model_candidate
  -> immutable promotion_policy_binding in candidate metrics/artifact
  -> ModelRegistry.metrics
  -> preregistered backtest STARTED.configuration
  -> experiment_governance_report selected trial
  -> evaluate_experiment_promotion_gate v2
  -> exact artifact + exact policy comparison
  -> current deployment-settings recheck
  -> atomic activation / audit / outbox
```

## 4. Baseline before changes

Comparable checks were executed in isolated environment `/mnt/data/cam_iter2_venv` because the host/global Python lacked `ruff`/project dependencies and had an unrelated Pillow/MoviePy conflict.

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no compile errors |
| `python -m ruff check .` | PASSED | no findings |
| `python -m pytest -q` | PASSED | 609 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |

No production code was changed before this baseline was recorded.

## 5. Confirmed defect

### DEFECT-1 — experiment evidence could authorize a different trading policy

- Classification: **CONFIRMED DEFECT**
- Severity: **critical**
- Area: econometrics / model lifecycle / trading-policy correctness
- Files:
  - `app/services/model_promotion.py::evaluate_experiment_promotion_gate`
  - `scripts/backtest.py` experiment configuration construction
  - `app/services/model_activation.py`
  - `app/ml/lifecycle.py::register_and_activate_model_candidate`

### Reproduction and evidence

The backtest ledger stores deployment-relevant fields including:

- `entry_spread_bps`
- `research_leverage`
- `liquidation_equity_reserve_fraction`
- `round_trip_cost_bps`
- `slippage_bps`
- `stop_gap_reserve_bps`
- `funding_rate_override`
- `timeout_return_rate_override`
- `minimum_net_rr`
- `minimum_net_ev_r`
- `policy_source`
- `portfolio_accounting`

Before 1.26.3, promotion verified only:

- `model_version`
- `model_sha256`
- `horizon`

A family could therefore select a trial with `slippage_bps=0` and `minimum_net_ev_r=-1`, while activation deployed only the model artifact and production continued with configured `slippage_bps=3` and `minimum_net_ev_r=0.05`.

Expected behavior: experiment evidence must describe the strategy actually deployed.
Actual behavior: a different policy configuration could authorize activation.
Impact: selected OOS Sharpe/PBO/DSR evidence was not necessarily evidence for the production strategy; this could invalidate promotion decisions and contribute to poor or unexpectedly sparse recommendations.

### Why previous tests missed it

Existing tests proved exact artifact binding and preregistration integrity but their synthetic selected configurations contained only version/SHA/horizon. They did not vary deployment-relevant costs or policy thresholds.

## 6. Change plan and actual diff

### Production files

- `app/services/model_promotion.py`
  - introduced `model-promotion-policy-binding-v1`;
  - raised experiment gate schema to v2;
  - validates and compares policy values key-by-key;
  - persists expected/selected/mismatch evidence;
  - invalidates stale or legacy gates.
- `app/ml/lifecycle.py`
  - persists binding when candidate policy metrics are generated;
  - requires candidate binding to match current deployment settings;
  - passes exact binding through fresh atomic activation.
- `app/services/model_activation.py`
  - requires persisted binding for normal registry activation;
  - compares it with current settings before state change;
  - passes binding into locked experiment re-evaluation.
- `app/workers/trainer.py`
  - requires binding during deferred reconciliation and fresh promotion evaluation;
  - legacy/malformed candidate binding becomes explicit `BLOCKED` state.
- `scripts/train.py`
  - manual activation path uses the same binding.
- `app/__init__.py`, `pyproject.toml`
  - version 1.26.3.

### Tests

- Added `tests/unit/test_experiment_policy_binding_2026_07_05.py`.
- Updated atomic, deferred and attrition fixtures to use promotion gate v2 and policy evidence.

### Documentation

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.26.3.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/QA_REPORT.md`
- this report

### Not changed

- database schema/migrations
- public HTTP API
- risk thresholds/defaults
- Bybit client or advisory-only boundary
- model prediction classes/features
- actual experiment PBO/DSR mathematics

## 7. Red -> green evidence

Initial regression command:

```text
python -m pytest -q tests/unit/test_experiment_policy_binding_2026_07_05.py
```

Before implementation:

```text
2 failed
TypeError: evaluate_experiment_promotion_gate() got an unexpected keyword argument 'expected_policy_binding'
```

The two initial tests independently specified:

1. exact artifact but non-production slippage/EV threshold must fail;
2. exact artifact and exact policy must pass.

After implementation and final assertions:

```text
4 passed
```

Additional assertions verify that changing deployment policy invalidates a previously passed gate and that legacy gates without policy binding fail closed.

## 8. Migration, API, configuration and compatibility

- Alembic migration: none.
- Alembic head remains `0014_ui_exposure_ledger`.
- `.env` additions: none.
- HTTP API: unchanged.
- Normal promotion gate schema: v1 -> v2.
- New candidates persist `promotion_policy_binding` in metrics/artifact metadata.
- Already active artifacts continue running; no automatic deactivation occurs.
- Inactive pre-1.26.3 candidates lack immutable policy evidence and must be retrained before normal activation.
- Explicit reasoned emergency rollback remains available and audited.

## 9. Post-change verification

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no compile errors |
| `python -m ruff check .` | PASSED | no findings |
| `python -m pytest -q` | PASSED | 613 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |
| version consistency | PASSED | app and package are 1.26.3 |
| static migration-head check | PASSED | one head: `0014_ui_exposure_ledger` |
| `python -B -m scripts.release_integrity --write` | PASSED | 214 eligible files / 214 manifest entries |

No previously green test regressed. Four new policy-binding assertions account for the increase from 609 to 613 passed tests.

## 10. Environment-dependent checks not completed

`python manage.py doctor` was run through a temporary project-local `.venv` link to the isolated environment and failed for environmental reasons:

- `.env` absent;
- default application secrets;
- `psql`, `pg_dump`, `pg_restore` absent;
- PostgreSQL unavailable at localhost:5432.

`python manage.py test --require-integration` could not start integration tests because neither `TEST_DATABASE_URL` nor `POSTGRES_ADMIN_URL` was configured.

These are reported as unavailable/not run integration evidence, not as passed checks.

## 11. Residual risks and limitations

1. Exact policy binding prevents evidence substitution but does not prove profitability.
2. Historical point-in-time funding forecast snapshots remain unavailable; the governed experiment contract uses zero additional funding stress override while realized historical settlements remain in realized PnL.
3. Historical orderbook depth before prospective storage, operator latency and exchange-accurate liquidation mechanics remain partial SPEC items.
4. Automatic creation/execution of a complete preregistered experiment family remains absent.
5. PostgreSQL concurrent-session behavior was not integration-tested in this environment.
6. Changing any bound policy field correctly requires new experiment evidence; this increases operator workload but prevents silent strategy substitution.

## 12. Rollback procedure

1. Stop trainer and API processes.
2. Restore the 1.26.2 source tree and restart processes; no database downgrade is required.
3. Do not manually copy a v2 gate into a 1.26.2 registry row.
4. If the active 1.26.3 artifact must be rolled back while retaining 1.26.3 code, use reviewed `model-registry activate` with matching evidence or explicit `--emergency-gate-override --override-reason ...`.
5. Re-run `doctor`, unit tests and PostgreSQL integration tests in the target environment.

## 13. Recommended next work package

Implement **automatic governed experiment-family orchestration after immutable candidate registration**: generate a preregistration draft from the exact candidate/cohort, require operator approval, execute the complete enumerated search budget, record failures/exclusions and expose progress. This should not weaken the new exact policy binding and must remain a separate iteration.
