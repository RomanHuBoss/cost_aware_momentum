# Iteration report — maturity-aware drift calibration

Date: 2026-07-05
Target version: `1.23.0`

## 1. Input archive and identification

- Input: `cost_aware_momentum-1.22.0-point-in-time-funding-intervals(1).zip`.
- SHA-256: `2fe0014423317a3bd005496b584257926050ae1581b12953f648e89166443a4f`.
- Source version: `1.22.0` (`app/__init__.py`, `pyproject.toml`).
- Python requirement: `>=3.12`; verification Python: `3.13.5`.
- Alembic migrations: 14; single head `0014_ui_exposure_ledger`.
- Initial inventory: 230 files, including 93 production files under `app/scripts/web`, 73 Python test files and 23 documentation files.
- The input archive contained one project root and no released `.env`, credential, cache, real model artifact or database dump.

## 2. Iteration goal and acceptance criteria

Goal:

> After this iteration, production calibration drift must use only complete full-horizon outcome cohorts, while early exits from immature signals are excluded and missing mature outcomes block evidence fail-closed.

Acceptance criteria:

1. An early TP/SL outcome before full horizon maturity does not enter calibration.
2. A full-horizon mature resolved outcome enters calibration normally.
3. Every mature signal is counted in the outcome denominator.
4. Missing outcome for any mature signal blocks calibration and the overall report.
5. Maturity coverage is explicitly disclosed in the JSON report.
6. Feature/probability PSI and actionability continue to use the full monitoring window.
7. Active model, artifact, policy thresholds, execution semantics and advisory-only boundary are unchanged.
8. Full pre-existing test suite remains green.

## 3. Sources read and affected data flow

Read before changes:

- `README.md`, `CHANGELOG.md`, `PATCH_1.19.0.md` through `PATCH_1.22.0.md`;
- `pyproject.toml` and repository configuration documentation;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- drift reference/evaluation, drift service, signal outcome resolver, worker heartbeat and production-drift tests.

Affected flow:

`MarketSignal(active model/window)` → horizon maturity partition → `SignalOutcome` completeness join → selected-direction calibration rows → drift report/outcome coverage → worker heartbeat.

Unaffected parallel flow:

all active-window signals → feature/probability PSI and actionability-density diagnostics.

## 4. Baseline

| Command | Status |
|---|---|
| `/mnt/data/cam_1210_venv/bin/python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `586 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

## 5. Confirmed defect

### CONFIRMED DEFECT — calibration drift was right-censored by immature early exits

- Severity: high econometric/operational correctness.
- File/function: `app/services/drift_monitor.py::build_production_drift_report`.
- Actual behavior: every resolved outcome in the active monitoring window entered calibration regardless of whether the signal's complete horizon had elapsed.
- Expected behavior: calibration should compare complete label opportunities. A signal is eligible only after `event_time + horizon_hours <= report time`.
- Minimal example:
  - signal A is six hours old with a four-hour horizon and a mature TIMEOUT;
  - signal B is one hour old with a four-hour horizon and already hit TP;
  - release 1.22.0 calibrated on both A and B even though a hypothetical TIMEOUT for B was structurally impossible to observe yet.
- Impact:
  - TP/SL could be overrepresented relative to TIMEOUT;
  - selected-direction log-loss/Brier could be falsely degraded;
  - drift status could become `CRITICAL` and heartbeat `DEGRADED` without genuine model deterioration;
  - unresolved mature outcomes could be silently omitted if enough other outcomes existed.
- Why tests missed it: prior tests passed already-assembled outcome rows directly to the mathematical evaluator and did not test horizon maturity at the service join boundary.

### DOCUMENTED LIMITATION — deterministic maturity correction

The patch uses full-horizon cohort restriction and complete-case enforcement. It does not fit a survival model or estimate inverse-probability-of-censoring weights.

## 6. Plan and actual diff

### Production

- `app/ml/drift.py`
  - report schema advanced to `production-drift-report-v2`;
  - added `full-horizon-mature-signal-outcomes-v1` cohort identifier.
- `app/services/drift_monitor.py`
  - validates timezone-aware event time and positive integer horizon;
  - partitions signals into mature/immature cohorts;
  - excludes immature early outcomes;
  - requires complete mature outcome coverage;
  - exposes maturity counts/rate and blocks invalid, duplicate or unresolved mature evidence.
- `app/__init__.py`, `pyproject.toml`
  - version `1.23.0`.

### Tests

- Added `tests/unit/test_drift_delayed_label_maturity_2026_07_05.py` with two service-level regressions.
- Existing production-drift tests were not weakened.

### Documentation

- Updated `README.md`, `CHANGELOG.md`, `PATCH_1.23.0.md`.
- Updated architecture, model card, configuration, operator manual, incident runbook, compliance, traceability and QA report.
- Added this iteration report.

### Migration/config/API

- No migration; head remains `0014_ui_exposure_ledger`.
- No `.env` setting change.
- No model artifact contract change or retraining requirement.
- No endpoint or browser contract change; the report JSON schema advances to v2 and gains `outcome_coverage`.

## 7. Red → green evidence

Command:

```bash
python -m pytest -q tests/unit/test_drift_delayed_label_maturity_2026_07_05.py
```

Before implementation:

```text
2 failed
assert 2 == 1
AssertionError: assert 'CRITICAL' == 'BLOCKED'
```

After implementation, together with the pre-existing drift suite:

```text
10 passed
```

## 8. Compatibility and rollback

- Existing active artifacts remain valid; no retraining is needed.
- Existing `DRIFT_*` values remain valid.
- Consumers reading `reports/production_drift.json` must tolerate report schema v2 and the new `outcome_coverage` object.
- Rollback: stop worker/API, restore 1.22.0 source and restart. No database downgrade or artifact rollback is required.

## 9. Post-check

| Command | Status |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `588 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

## 10. Not verified

- PostgreSQL integration suite: not run because no isolated `TEST_DATABASE_URL` was supplied.
- Live outcome resolver and live drift report against PostgreSQL: not run.
- Live Bybit behavior: not run and not affected.
- Profitability, forward edge and recommendation frequency: not claimed or verified.

## 11. Residual risks

1. Maturity filtering reduces the number of calibration observations by up to the maximum active horizon near the end of each window.
2. Missing mature outcomes now block the report, but their operational root cause still requires candle/outcome-resolver diagnostics.
3. Deterministic complete-case maturity correction does not model informative censoring or varying resolution hazards.
4. Multivariate drift tests, adaptive control limits and automatic rollback remain unimplemented.
5. A green drift report remains monitoring evidence, not proof of profitability.

## 12. Rollback procedure

1. Preserve the 1.23 drift report and logs for audit.
2. Stop API and worker processes.
3. Restore the 1.22.0 source tree.
4. Restart without database downgrade or model change.
5. Treat v2 reports as incompatible with any strict v1-only external parser.

## 13. Recommended next work package

Implement a fail-closed candidate and live recommendation attrition funnel that attributes every scoped opportunity to data incompleteness, model quality gates, policy economics, overlap suppression, spread/liquidity, capital/margin, portfolio caps or minimum-order blocking. This directly addresses rare recommendations and trained candidates that do not pass gates without weakening thresholds.

## 14. Release archive verification

- Clean stage root: `cost_aware_momentum-1.23.0`.
- Files: 233 including `SHA256SUMS`; 232 checksum entries.
- Forbidden cache/credential/build/model/database artifacts: absent after staged verification cleanup.
- Staged full suite: `588 passed, 4 skipped, 61 warnings`; `pip check`, compileall, Ruff, Node syntax and Alembic head passed.
- Trailing-whitespace, suspicious-secret and Bybit order-mutation scans passed.
- Final ZIP is tested with `unzip -t`, re-extracted into a clean directory and checked again against `SHA256SUMS` and the same static/test commands.
- The ZIP hash is provided externally because a file cannot contain its own stable archive hash.
