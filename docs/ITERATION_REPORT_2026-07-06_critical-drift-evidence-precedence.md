# Iteration report — critical drift evidence precedence

## 1. Input and source state

- Input archive: `cost_aware_momentum-1.28.0-risk-budgeted-experiment-accounting(1).zip`.
- Input SHA-256: `f85389e3753cbd4bb24034cfbcae7479e260300066dbf58545338a3eb0eb2b3d`.
- Source release: 1.28.0.
- Target release: 1.28.1.
- Python requirement: >=3.12; checks executed with Python 3.13.5 in `/mnt/data/cam_iter2/venv`.
- Database revisions: 14; single Alembic head `0014_ui_exposure_ledger`.
- Source inventory: 231 files; 93 production Python, 85 test Python, 12 documentation files.

## 2. Iteration objective and acceptance criteria

Objective:

> After this iteration, independently confirmed critical production-drift evidence must always produce a `CRITICAL` report and exact-version publication quarantine even when another evidence dimension is incomplete, while incomplete-only warm-up/outcome evidence remains `BLOCKED` and non-quarantining.

Acceptance criteria:

1. Critical feature/probability/actionability evidence cannot be overwritten by low coverage, failed jobs or incomplete outcome evidence.
2. Valid calibration critical evidence produces `CRITICAL`; incomplete maturity invalidates calibration-only evidence before status resolution.
3. Empty/sub-minimum warm-up remains `BLOCKED` rather than creating a false missingness critical.
4. Report exposes separate critical, blocking and warning reason lists.
5. Existing persisted critical guard and exact-model-version semantics remain unchanged.
6. No recommendation threshold, model artifact, DB, API or `.env` contract changes.
7. New tests fail on source 1.28.0 and pass after the fix.
8. Full static/unit suite remains green.

## 3. Sources read and affected data flow

Read before the change:

- `README.md`, `CHANGELOG.md`, `PATCH_1.28.0.md`, `PATCH_1.27.0.md`, `PATCH_1.26.7.md`;
- `pyproject.toml`, `.env.example`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- the latest risk-accounting and critical-drift iteration reports;
- `app/ml/drift.py`, `app/services/drift_monitor.py`;
- `app/workers/runner.py`, publication guard and signal/plan interlock tests;
- production drift, delayed-label maturity and critical-interlock unit tests.

Relevant flow before the fix:

`active model reference → production feature/probability/outcome/coverage evidence → mutable overall status → service-level direct BLOCKED overwrite → persisted JobRun → guard queries only overall CRITICAL → inference/publication`.

Flow after the fix:

`active model reference → independent critical/blocking/warning evidence lists → maturity invalidates calibration-only evidence → deterministic final status → persisted JobRun → exact-version critical guard → inference/publication quarantine`.

## 4. Baseline

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no syntax errors |
| `python -m ruff check .` | PASSED | no findings |
| `python -m pytest -q` | PASSED | 641 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |
| `python manage.py doctor` | FAILED preflight | project-local managed virtualenv absent |
| `python manage.py test --require-integration` | FAILED preflight | project-local managed virtualenv absent; PostgreSQL integration not executed |

## 5. Confirmed defect

### CONFIRMED DEFECT — BLOCKED status suppresses independent critical drift

Severity: **critical safety / high operational**.

Files/functions:

- `app/ml/drift.py::_STATUS_RANK`, `_status_max`, `evaluate_production_drift`;
- `app/services/drift_monitor.py::build_production_drift_report`;
- downstream `app/services/drift_monitor.py::production_drift_publication_guard`.

Actual behavior:

- `BLOCKED` ranked above `CRITICAL`;
- incomplete coverage or observations could make overall status `BLOCKED` after a critical PSI/missingness/probability/calibration/actionability result;
- service post-processing directly assigned `report["status"] = "BLOCKED"` for failed jobs, invalid accounting and incomplete mature outcomes;
- publication guard searches persisted reports with exact overall status `CRITICAL`, so such a report did not latch quarantine.

Expected behavior:

- valid independent critical evidence must trigger critical quarantine;
- blockers must remain visible but cannot erase critical evidence;
- calibration evidence must be removed when maturity/outcome integrity is incomplete;
- pure incomplete warm-up must remain blocked and non-quarantining.

Minimal reproduced example:

```text
feature PSI = 11.512865346214785
coverage = 6 / 10 = 0.60, required >= 0.80
alerts = [insufficient_inference_coverage, feature_distribution_drift]
source overall status = BLOCKED
expected safety status = CRITICAL
```

Impact:

- active model could continue publishing recommendations after a severe independently observed distribution shift;
- losses during such a period would not be prevented by the existing critical interlock;
- this is a safety defect, not proof that all historical losses were caused by drift.

Why existing tests missed it:

Existing tests separately checked critical drift and blocked evidence. They did not combine both in one report and assert that independent critical evidence has safety precedence while calibration-only invalid evidence is removed.

## 6. Plan and actual diff

Production:

- `app/ml/drift.py`:
  - report schema v2 → v3;
  - explicit critical/blocking/warning evidence lists;
  - deterministic status resolver;
  - missingness critical only after minimum denominator exists.
- `app/services/drift_monitor.py`:
  - service-level blockers merge into evidence instead of overwriting status;
  - incomplete/invalid maturity invalidates calibration-only evidence;
  - final status recomputed after all integrity checks.

Tests:

- new `tests/unit/test_critical_drift_evidence_precedence_2026_07_06.py`;
- strengthened `tests/unit/test_production_drift_monitoring_2026_07_05.py`;
- strengthened `tests/unit/test_drift_delayed_label_maturity_2026_07_05.py`.

Docs/release:

- `README.md`, `CHANGELOG.md`, `PATCH_1.28.1.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this iteration report;
- `pyproject.toml`, `app/__init__.py`, regenerated `SHA256SUMS`.

Migration/API/config:

- no migration;
- no HTTP contract change;
- no new `.env` variable;
- no model artifact or recommendation-policy change.

## 7. Red → green evidence

Red command:

```text
python -m pytest -q tests/unit/test_critical_drift_evidence_precedence_2026_07_06.py
```

Red result on source behavior:

```text
2 failed, 1 passed
AssertionError: expected CRITICAL, actual BLOCKED
```

The failing paths were:

1. severe feature drift plus low inference coverage;
2. severe feature drift plus incomplete mature outcomes.

Green targeted result after implementation:

```text
3 passed
```

Combined drift/maturity/interlock suite:

```text
20 passed
```

The third test is a negative control: incomplete outcomes with reference-matching independent evidence remain `BLOCKED` and do not request quarantine.

## 8. Compatibility and rollback

- DB migration: none.
- Active artifact/runtime compatibility: preserved.
- Old persisted v2 report with overall `CRITICAL`: still recognized by existing guard.
- New v3 reports add evidence lists; consumers that only read `status`, `alerts` and existing metric sections remain compatible.
- No thresholds were lowered or raised.

Rollback procedure:

1. Restore release 1.28.0 source tree and its `SHA256SUMS`.
2. No database downgrade is required.
3. Be aware that rollback reintroduces the status-precedence defect for future drift reports.
4. Existing persisted `CRITICAL` reports continue to quarantine under either release.

## 9. Post-change checks

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no syntax errors |
| `python -m ruff check .` | PASSED | no findings |
| `python -m pytest -q` | PASSED | 644 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |
| Alembic head inspection | PASSED | one head, `0014_ui_exposure_ledger` |
| version consistency | PASSED | 1.28.1 in package/application sources |
| final release inventory | PASSED | 234 files including `SHA256SUMS`; 93 production Python, 86 test Python, 13 files under `docs/` |
| release integrity | PASSED | 233 eligible files checked against 233 regenerated manifest entries |
| ZIP test/re-extraction | PASSED | one project root, compressed-data test clean, re-extracted manifest verified |

## 10. Not verified

- PostgreSQL integration/concurrency tests: project-managed runtime and separate test DB are unavailable.
- Full persisted v3 JobRun lifecycle on PostgreSQL across a real worker restart.
- Real production data proving which historical recommendations occurred during a masked critical-drift state.
- Symbol-specific or regime-specific drift behavior.
- Profitability and causal attribution of losses.

## 11. Residual risks and limitations

- Aggregate univariate PSI can still hide offsetting subgroup/symbol drift.
- Static thresholds may be too sensitive or insensitive across regimes.
- A `CRITICAL` report quarantines the whole exact model version, not a single symbol or feature.
- Recovery still requires activation of another governed model version; automatic rollback is intentionally absent.
- Incomplete-only evidence remains non-quarantining to avoid a permanent bootstrap deadlock.

## 12. Recommended next work package

Implement symbol/regime-conditional production drift diagnostics with minimum-denominator and multiple-testing governance, then quarantine only when the conditional evidence is independently strong enough. This should be done without weakening the current exact-version global interlock and without claiming causal profitability.
