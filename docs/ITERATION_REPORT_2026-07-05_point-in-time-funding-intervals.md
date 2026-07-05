# Iteration report — point-in-time funding intervals

Date: 2026-07-05
Target version: `1.22.0`

## 1. Input archive and identification

- Input: `cost_aware_momentum-main.zip`.
- SHA-256: `64c82a5cb35ff75934f13a58f63ede67ef61c295f34ae3fb8fed8e5fe83eb3ce`.
- Source version: `1.21.0` (`app/__init__.py`, `pyproject.toml`).
- Python requirement: `>=3.12`; verification Python: `3.13.5`.
- Alembic migrations: 14; single head `0014_ui_exposure_ledger`.
- Initial inventory: 93 production files under `app/scripts/web`, 72 test files and 22 documentation files.
- Input archive contained one project root and no released `.env`, credential, real model artifact or database dump. Test execution later created caches and `egg-info`; these are excluded from the release archive.

## 2. Iteration goal and acceptance criteria

Goal:

> After this iteration, research settlement replay and market-context funding age must use the funding interval effective at each historical timestamp, while missing settlements remain fail-closed and legacy artifacts cannot be activated under the new semantics.

Acceptance criteria:

1. A complete observed 8-hour to 4-hour interval transition is accepted.
2. A missing settlement after the transition is rejected.
3. `funding_age_fraction` is divided by the interval effective at each decision time.
4. Background trainer, manual train and backtest receive full interval history.
5. Candidate metrics disclose point-in-time source, changes and backward assumptions.
6. Promotion/runtime reject legacy and fallback-only artifact semantics.
7. No migration, `.env` or advisory-only boundary change is introduced.
8. Full pre-existing test suite remains green.

## 3. Sources read and affected data flow

Read before changes:

- `README.md`, `CHANGELOG.md`, `PATCH_1.18.0.md` through `PATCH_1.21.0.md`;
- `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- funding/context/training/lifecycle/runtime modules, trainer and backtest/manual-training entry points;
- funding, context, artifact, recovery, quality-gate and econometric regression tests.

Affected flow:

`InstrumentSpecHistory` → `load_training_market_data` → `FundingIntervalSchedule` → historical settlement completeness and funding-age context → barrier dataset → model metrics/artifact → promotion gate/runtime/backtest.

## 4. Baseline

Authoritative isolated baseline:

| Command | Status |
|---|---|
| `/mnt/data/cam_1210_venv/bin/python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `582 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

The global host result was not authoritative: required packages were absent and an unrelated dependency conflict existed.

## 5. Confirmed defect

### CONFIRMED DEFECT — latest funding interval was retroactively applied to all history

- Severity: high model/econometric correctness; potentially critical for a symbol whose interval changed within the training window.
- Files/functions:
  - `app/ml/lifecycle.py::load_training_market_data`;
  - `app/ml/funding.py::HistoricalFundingTimeline`;
  - `app/ml/context.py::_attach_latest_settled_funding`.
- Actual behavior: spec rows were ordered newest-first and collapsed to the first positive value per symbol. That fixed value drove every historical completeness check and funding-age observation.
- Expected behavior: select the interval effective at each event/decision timestamp from the append-only spec history.
- Minimal example: actual settlements at 00/08/16/24 hours under 8-hour cadence, then 28/32 under 4-hour cadence. With latest interval 4 hours, the old 8-hour sequence was falsely interpreted as missing 04/12/20 settlements.
- Impact:
  - valid historical cohorts could be discarded;
  - background training could fail before quality-gate evaluation;
  - old `funding_age_fraction` values could be inflated and marked stale;
  - candidate/incumbent comparisons could be performed on a distorted or reduced cohort.
- Why tests missed it: all previous replay/context tests supplied one constant interval mapping.

### DOCUMENTED LIMITATION — pre-observation interval history

`InstrumentSpecHistory` is populated prospectively when instrument sync observes a changed fingerprint. For timestamps before the first local row, exact historical interval is unknown. Version 1.22.0 uses the earliest observed interval and records the affected symbols as a backward assumption. It does not claim reconstructed history.

## 6. Plan and actual diff

### Production

- `app/ml/funding.py`: point-in-time schedule, transition-aware completeness, metadata and schema v2.
- `app/ml/context.py`: decision-time interval lookup and context schema v2.
- `app/ml/training.py`: interval history parameter; feature schema v5 and policy schema v16.
- `app/ml/lifecycle.py`: preserve all positive spec-history rows; pass them to candidate build; enforce schedule evidence.
- `app/ml/runtime.py`: reject artifacts without the point-in-time schedule contract.
- `app/workers/trainer.py`, `scripts/train.py`, `scripts/backtest.py`: pass full interval history.
- `app/__init__.py`, `pyproject.toml`: version 1.22.0.

### Tests

- Added `tests/unit/test_point_in_time_funding_intervals_2026_07_05.py` with four regressions.
- Updated artifact/quality-gate fixtures in existing unit tests to the new semantic contracts; test intent and thresholds were not weakened.

### Documentation

- Updated `README.md`, `CHANGELOG.md`, `PATCH_1.22.0.md`.
- Updated architecture, model card, operator manual, incident runbook, compliance, traceability and QA report.
- Added this iteration report.

### Migration/config/API

- No migration.
- Alembic head remains `0014_ui_exposure_ledger`.
- No new or changed `.env` variable.
- No HTTP/API schema change.
- No Bybit mutation method or order lifecycle was added.

## 7. Red → green evidence

Initial command:

```bash
python -m pytest -q tests/unit/test_point_in_time_funding_intervals_2026_07_05.py
```

Before production implementation: `3 failed`; replay and context rejected the new interval-history arguments with `TypeError`.

After implementation:

```text
4 passed
```

The fourth test verifies explicit disclosure when funding history predates the first local spec observation.

## 8. Compatibility and rollback

- Old artifacts are intentionally incompatible. Semantic version bumps prevent silent reuse of models trained with the wrong historical interval geometry.
- Required user action: synchronize instruments/funding data, retrain a candidate, inspect interval metadata and pass normal gates before activation.
- Rollback: stop trainer/API, restore 1.21.0 source and the preserved 1.21.0-compatible active artifact. No database downgrade is necessary.

## 9. Post-check

| Command | Status |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests migrations manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `586 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |

## 10. Not verified

- PostgreSQL integration suite: not run because no isolated `TEST_DATABASE_URL` was supplied.
- Live PostgreSQL query and real trainer run: not run.
- Live Bybit network behavior: not run; no API change was needed.
- `manage.py doctor` under a project-local `.venv`: not run; invocation through the external isolated venv correctly reported that the release tree has no local `.venv`.
- Profitability, forward edge and increased recommendation frequency: not claimed or verified.

## 11. Residual risks

1. Exact intervals before the first locally observed spec row remain unknown.
2. A transition is validated from observed spec and settlement events; unavailable historical exchange schedule announcements are not reconstructed.
3. Point-in-time funding forecasts remain absent, so expected funding is still a separate conservative stress input rather than a learned forecast.
4. This fix can recover falsely excluded cohorts only where interval changes exist; it does not explain every sparse-signal or loss episode.
5. Full economic validation still requires new OOS/forward evidence after retraining.

## 12. Rollback procedure

1. Preserve the 1.22 candidate/artifact and logs for audit.
2. Stop API and trainer processes.
3. Restore the 1.21.0 source tree and its previously preserved active artifact.
4. Restart without database downgrade; head `0014_ui_exposure_ledger` is common to both releases.
5. Do not load a 1.22 artifact in 1.21 or edit artifact metadata manually.

## 13. Recommended next work package

Add a fail-closed candidate-attrition funnel that attributes every potential decision timestamp to data incompleteness, label construction, ML absolute gate, incumbent-relative gate, policy economics or execution/risk blocking. This should diagnose the user's “rare recommendation / models do not pass gates” symptom without lowering thresholds or claiming profitability.

## 14. Release archive verification

- Clean stage root: `cost_aware_momentum-1.22.0`.
- Files: 230 including `SHA256SUMS`; 229 checksum entries verified.
- Forbidden cache/credential/build/model/database artifacts: absent.
- Suspicious-secret, trailing-whitespace and Bybit order-mutation scans: passed.
- Staged full suite: `586 passed, 4 skipped, 61 warnings`; compileall, Ruff, Node syntax and Alembic head passed.
- Final ZIP was tested with `unzip -t`, re-extracted into a clean directory and verified again against `SHA256SUMS` and the same full static/test commands.
- The ZIP hash is provided externally in the delivery response to avoid a self-referential checksum.
