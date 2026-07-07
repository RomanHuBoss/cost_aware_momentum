# Iteration report — trainer preflight scope alignment

Date: 2026-07-07
Target release: 1.38.0

## 1. Input archive and baseline identity

- Input: `cost_aware_momentum-1.37.0-executable-spread-replay-alignment.zip`
- SHA-256: `a6e9ce6dfa0b1c6615378d06e4e945513b4d80295cd4b13a3f5eefc9787de895`
- Source version: 1.37.0
- Python requirement: >=3.12
- Runtime: Python 3.13.5
- Alembic head: `0017_model_artifact_blobs`
- Baseline inventory: 102 production/script/web files, 102 test files, 15 documentation files, 17 migration revisions.

## 2. Objective and acceptance criteria

Objective:

> After this iteration, every background candidate must be fitted on the exact symbols and latest label-eligible cutoff that caused the scheduler to authorize training, and promotion must fail closed if feature/context/label construction materially changes that scope.

Acceptance criteria:

1. Missing or malformed trigger profile blocks background training.
2. Dynamic mode uses exact preflight symbols rather than an unlimited re-selection.
3. Last, mark and index candles are capped at the persisted preflight horizon.
4. The cap retains exactly one configured label horizon after the latest eligible decision.
5. Actual candidate symbols are compared with preflight symbols.
6. Post-feature symbol coverage satisfies `AUTO_TRAIN_MIN_SYMBOL_COVERAGE_RATIO`.
7. Candidate data cannot advance beyond the preflight cutoff.
8. Existing model/risk/promotion thresholds are unchanged.

## 3. Sources and affected flow

Read before modification:

- `README.md`, `CHANGELOG.md`, `PATCH_1.35.5.md`, `PATCH_1.36.0.md`, `PATCH_1.37.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- `app/config.py`, `app/workers/trainer.py`;
- `app/ml/lifecycle.py`, `app/ml/data_profile.py`, `app/ml/training.py`;
- related trainer, lifecycle, universe and quality-gate tests.

Affected flow:

`PostgreSQL candles + universe snapshots → current_training_profile → persisted trainer trigger → exact symbols/cutoff resolver → bounded last/mark/index loader → feature/context/label dataset → candidate training profile → quality gate → registry/promotion`.

## 4. Baseline

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | FAILED — unrelated global moviepy/Pillow conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 744 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |

PostgreSQL integration and `manage.py doctor` were not run because no isolated/operator configuration was available.

## 5. Confirmed defects

### DEFECT-1 — dynamic symbol cohort changed after preflight

Classification: `CONFIRMED DEFECT`
Severity: HIGH

Files/functions:

- `app/workers/trainer.py::current_training_profile`
- `app/workers/trainer.py::run_training_once`

Evidence:

- preflight called `load_training_data_profile(... max_symbols=AUTO_TRAIN_MAX_SYMBOLS)`;
- trigger persisted `training_data_profile.symbols`;
- fit extracted trigger symbols only under `UNIVERSE_MODE=static`;
- dynamic fit used `symbols=None, max_symbols=0`.

Impact: scheduler sufficiency and fitted candidate were evaluated on different cohorts.

### DEFECT-2 — fit horizon advanced after authorization

Classification: `CONFIRMED DEFECT`
Severity: HIGH

File/function: `app/ml/lifecycle.py::load_training_market_data`

Evidence: loader always derived its upper boundary from the latest database candle and had no `as_of`/maximum-open-time argument.

Impact: later candles and universe snapshots could change the candidate after the trigger had been persisted.

### DEFECT-3 — actual fitted coverage was not promotion-bound

Classification: `CONFIRMED DEFECT`
Severity: MEDIUM

File/function: `app/ml/lifecycle.py::evaluate_quality_gate`

Evidence: the gate evaluated holdout/policy/model evidence but did not compare `candidate.training_data_profile` with the preflight profile or enforce the configured symbol coverage after full dataset construction.

Impact: expected symbols lost through missing OI/mark/index/funding context or label continuity had no dedicated fail-closed reason.

## 6. Plan and actual diff

Production:

- `app/workers/trainer.py`
  - added strict trigger-profile resolver;
  - exact symbols and temporal bound forwarded to fit;
  - expected profile passed to quality gate.
- `app/ml/lifecycle.py`
  - added bounded last/mark/index loading;
  - added expected-versus-actual training-scope gate evidence and reasons.
- `app/__init__.py`, `pyproject.toml`
  - version 1.38.0.

Tests:

- `tests/unit/test_preflight_training_scope_alignment_2026_07_07.py`.

Documentation:

- `README.md`, `CHANGELOG.md`, `PATCH_1.38.0.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this report.

No migration or `.env` change.

## 7. Red → green evidence

Command:

```text
python -m pytest -q tests/unit/test_preflight_training_scope_alignment_2026_07_07.py
```

Untouched 1.37.0: **6 failed**.

Material failures:

- missing strict trigger-profile resolver;
- loader rejected `maximum_open_time` as an unknown argument;
- quality gate rejected `expected_training_profile` as an unknown argument.

After correction: **6 passed**.

The tests independently verify symbol/cutoff resolution, malformed-trigger rejection, SQL upper bounds for all three candle types, post-feature coverage rejection and symbol/time drift rejection.

## 8. Compatibility

- Database migration: none.
- Alembic head: unchanged `0017_model_artifact_blobs`.
- API contract: unchanged.
- `.env`: unchanged.
- Manual training: compatible; new loader/gate inputs are optional.
- Background trainer: existing due/operator recovery triggers already contain the required profile.
- Rollback: stop trainer, restore 1.37.0 files, restart. No database rollback is necessary.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| focused regression | PASSED — 6 passed |
| focused compatibility | PASSED — 33 passed |
| `python -m pytest -q` | PASSED — 750 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — one head |

## 10. Not verified

- Actual PostgreSQL background run and transaction timing.
- Runtime behavior on the operator database.
- Exact stage at which the operator's current history loses rows.
- Economic performance or actual fill quality.

## 11. Residual risks and limitations

- Preflight remains a candle/replay coverage check, not a full zero-cost dry construction of all features and labels. The new candidate gate catches divergence after fit but cannot avoid all wasted fit attempts.
- A symbol with enough candles but incomplete historical OI/mark/index/funding may be rejected only after dataset construction.
- Historical dynamic membership before the immutable ledger cannot be reconstructed.
- A reproducible candidate is not evidence of profitability.

## 12. Recommended next work package

Add a non-fitting, stage-by-stage training eligibility audit that reports counts after:

`confirmed last candles → strict continuity → mark/index/OI/funding completeness → universe/spread replay → barrier labels → split/holdout/walk-forward`.

This should use the exact frozen preflight scope introduced here and expose the bottleneck in trainer status/UI without weakening any gate.
