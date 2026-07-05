# Iteration Report — 2026-07-05 — production drift monitoring

## 1. Input and baseline identity

- Input archive: `cost_aware_momentum-1.16.0-market-context-features(1).zip`
- Input SHA-256: `9bfd32ad4907b37790111b583e7f91e6f0faf603da8634160d23754820ef143e`
- Input version: 1.16.0
- Input Alembic head: `0011_selection_experiment`
- Baseline: 531 passed, 4 skipped; Ruff, compileall, frontend syntax, pip dependency check and single Alembic head passed.

## 2. Goal and acceptance criteria

Goal: after this iteration, the system must compare production observations for the active model with an immutable, cohort-compatible final-holdout reference and expose fail-closed drift diagnostics without silently changing model or risk policy.

Acceptance criteria:

1. Candidate artifact contains fixed feature/probability references derived only from final holdout.
2. Calibration baseline uses the same selected-direction population as production outcomes.
3. Production signals preserve both directional probability vectors without changing selected signal semantics.
4. Monitor reports coverage, missingness, feature/probability PSI, calibration and actionability drift for one active model version.
5. Failed inference jobs, insufficient evidence and invalid accounting produce `BLOCKED`.
6. `CRITICAL/BLOCKED` appears as degraded operational health.
7. No automatic model activation/deactivation/rollback or gate weakening occurs.
8. Runtime, quality gate, CLI, daily report, configuration, tests and documentation share one contract.

## 3. Sources and data flow

Read: README, changelog, recent patch reports, architecture, QA, compliance, traceability, model card, configuration, security, incident runbook, operator manual, model lifecycle/runtime, signal publication, worker, database models and tests.

Data flow:

final holdout → fixed artifact reference → active-version signal feature/probability snapshots → hourly inference JobRun coverage → resolved SignalOutcome calibration evidence → drift evaluator → JobRun details, worker heartbeat and JSON reports.

## 4. Baseline

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 531 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m alembic heads` | PASSED | `0011_selection_experiment`. |

## 5. Confirmed gap and risk

### CONFIRMED GAP — high

`docs/SPEC_COMPLIANCE.md` marked production drift monitoring as not implemented. The 1.16.0 artifact contained final-holdout performance and context-ablation evidence but no fixed production reference, and the worker had no active-version service for PSI, coverage, missingness, calibration or actionability drift.

Impact: a technically valid artifact could remain active while its input distribution, output probabilities, calibration or recommendation density materially changed. Operators had no reproducible evidence separating insufficient monitoring data from a healthy model.

Why existing tests did not catch it: tests covered temporal validation, artifact compatibility and activation gates, not post-activation distribution monitoring.

### CONFIRMED DESIGN HAZARD — high

Production outcomes exist only for the policy-selected LONG/SHORT signal. Using all hypothetical direction rows as the calibration baseline would compare different populations and generate misleading calibration deltas. The implemented reference therefore stores probability distributions for both directions but calibration metrics only for the selected-direction final-holdout cohort.

## 6. Actual changes

Production/research:

- `app/ml/drift.py`: immutable references, fixed-bin PSI, missingness/coverage, calibration and actionability evaluation.
- `app/ml/training.py`: selected-direction final-holdout calibration evidence.
- `app/ml/lifecycle.py`: artifact/reference construction and promotion checks.
- `app/ml/runtime.py`: strict reference/cohort validation and metadata.
- `app/services/signals.py`: both directional probability vectors in the signal snapshot.
- `app/services/drift_monitor.py`: active-version database collection and report assembly.
- `app/workers/runner.py`: hourly monitoring and heartbeat degradation.
- `scripts/drift_report.py`, `scripts/daily_report.py`, `manage.py`, `pyproject.toml`: CLI/report integration.
- `app/config.py`, `.env.example`: validated drift thresholds.

Tests:

- Added `tests/unit/test_production_drift_monitoring_2026_07_05.py`.
- Added reusable valid reference fixture in `tests/drift_reference.py`.
- Updated artifact/quality-gate fixtures for the mandatory contract.
- Added runtime rejection of an unselected calibration cohort.

Documentation/version:

- Version 1.17.0 in package and project metadata.
- Added `PATCH_1.17.0.md` and changelog entry.
- Updated README, compliance, traceability, architecture, configuration, model card, operator manual, security, incident runbook and QA report.

## 7. Red → green evidence

Command on untouched 1.16.0:

```text
python -m pytest -q tests/unit/test_production_drift_monitoring_2026_07_05.py
```

Red:

```text
ModuleNotFoundError: No module named 'app.ml.drift'
```

Green after implementation:

```text
8 passed
```

Full suite: 531 → 540 passing tests, with the same 4 PostgreSQL skips.

## 8. Migration, API and configuration compatibility

- Database migration: none; head remains `0011_selection_experiment`.
- Existing JSON fields store references/reports; no table or endpoint breaking change.
- New optional `DRIFT_*` environment settings have validated defaults.
- Artifact compatibility is intentionally broken: pre-1.17 artifacts lack the reference and must be retrained.
- Advisory-only and read-only Bybit boundaries are unchanged.

## 9. Post-check

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | No broken requirements. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 540 passed, 4 skipped, 61 warnings. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m alembic heads` | PASSED | Single head `0011_selection_experiment`. |

## 10. Not verified

- PostgreSQL integration tests: skipped because `TEST_DATABASE_URL` is not configured.
- Migration execution: not applicable; no migration added.
- `manage.py doctor`: environment failure because the release tree has no project-local `.venv`.
- Real multi-day production drift accumulation and delayed outcome resolution.
- Full retraining on the user's production database.
- Paper/shadow response procedures for actual drift alerts.

## 11. Residual risks and limitations

- PSI is univariate and sensitive to chosen bins/thresholds.
- Calibration evidence is delayed by the strategy horizon and outcome resolver.
- No confidence intervals or delayed-label adjustment are applied to drift deltas.
- Universe-composition changes can legitimately alter marginal distributions.
- No automatic rollback/deactivation is performed by design.
- Monitoring does not establish causal degradation or profitability.

## 12. Rollback

1. Stop API, worker and trainer.
2. Restore source version 1.16.0 and its compatible active artifact/registry backup.
3. No database downgrade is required.
4. Restore the previous `.env` if `DRIFT_*` values were added.
5. Run `doctor`, static checks and a paper/shadow smoke cycle before resuming operation.

Do not attempt to make a 1.16.0 artifact compatible by manually adding metadata.

## 13. Recommended next work package

Implement PBO/Deflated Sharpe and a complete experiment-selection ledger over the existing purged walk-forward/backtest evidence. This should quantify multiple-testing and selection inflation without reusing final holdout data and without representing the resulting statistic as proof of profitability.
