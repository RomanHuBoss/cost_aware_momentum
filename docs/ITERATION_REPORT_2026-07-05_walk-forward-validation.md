# Iteration Report — purged expanding walk-forward validation

## 1. Input archive and baseline identity

- Input archive: `cost_aware_momentum-1.10.0-execution-entry-alignment(1).zip`
- SHA-256: `8a30282ebd65c7876052eef01e72f1f00a00487c244bcd36f0d6156aa4ef4597`
- Source version: 1.10.0
- Target version: 1.11.0
- Python requirement: >=3.12; executed on 3.13.5
- Database migrations: 9; unchanged head `0009_candle_receipt_availability`
- Source tree before changes: 74 production/script/web files, 61 test files, 11 files under `docs/`, 9 migration revisions.

## 2. Iteration goal and acceptance criteria

Goal:

> After this iteration, every model candidate must provide reproducible temporal-stability evidence from three purged expanding walk-forward folds built strictly before a separate final holdout, and auto-activation must fail closed when that evidence is absent, malformed, overlapping or materially unstable.

Acceptance criteria:

1. Final holdout rows are never used by development walk-forward folds.
2. Each fold uses expanding train, rolling calibration and a later non-overlapping test window.
3. Boundaries preserve whole decision timestamps and LONG/SHORT scenario pairs.
4. `label_end_time` overlap is purged and horizon embargo is applied.
5. A fresh model pipeline and calibration are fit in every fold.
6. Artifact/runtime schemas make pre-1.11 temporal evidence incompatible fail-closed.
7. Gate requires three valid folds and positive ML skill/policy mean in at least two folds.
8. Full pre-existing unit suite remains green.

## 3. Sources read and changed data flow

Reviewed:

- `README.md`, `CHANGELOG.md`, `PATCH_1.10.0.md`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- `pyproject.toml`, `.env.example`;
- specification DOCX sections requiring sequential windows, overlap purging, embargo, expanding/rolling walk-forward inside development period, one untouched final holdout and later paper/shadow evidence;
- `app/ml/training.py`, `app/ml/lifecycle.py`, `app/ml/runtime.py`, trainer/backtest call paths and related tests.

Changed flow:

`confirmed hourly candles → point-in-time features/labels → final chronological split → development-only expanding walk-forward folds → fresh fold model/calibration → fold ML/policy evidence → final holdout metrics → quality gate → immutable artifact/runtime validation`.

## 4. Baseline

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED | External host conflict: moviepy requires Pillow <12, host has 12.2.0. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0 |
| `python -m ruff check .` | PASSED | Exit 0 |
| `python -m pytest -q` | PASSED | 468 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED | Exit 0 |
| `python manage.py doctor` | FAILED (environment) | `.venv` absent |
| PostgreSQL integration | NOT RUN | No isolated test database configured |

## 5. Confirmed gap and evidence

### HIGH — single temporal split could not demonstrate regime stability

Classification: `CONFIRMED GAP`.

Evidence before change:

- `app/ml/training.py::chronological_split()` produced one 70% train / 15% calibration / 15% final-holdout partition.
- `app/ml/lifecycle.py::build_model_candidate()` trained one model and evaluated only that one final split.
- `docs/SPEC_COMPLIANCE.md` explicitly marked rolling/expanding walk-forward as not implemented.
- The product specification requires sequential windows with purge/embargo, expanding/rolling walk-forward inside development period, and a separately fixed final holdout.

Impact:

- one favourable historical boundary could pass despite poor adjacent regimes;
- calibration and policy stability over time were unmeasured;
- auto-activation had no fold-level evidence to distinguish robust performance from temporal concentration.

Why tests did not catch it: the function and artifact contract did not exist. Existing tests correctly validated the one-split protocol but could not assert a missing multi-window process.

This iteration does not classify absent PBO, historical orderbook, funding settlement replay, selection-bias correction or drift monitoring as fixed.

## 6. Plan and actual diff

### Production

- `app/ml/training.py`
  - introduced temporal/walk-forward schema constants;
  - added minimum-history accounting for folds;
  - extracted common split conversion;
  - added `expanding_walk_forward_splits()` with whole-timestamp boundaries, purge, embargo and non-overlapping tests.
- `app/ml/lifecycle.py`
  - added fresh per-fold training/calibration and fold evaluation;
  - persisted detailed fold evidence;
  - strengthened quality gate with structural, temporal, arithmetic, worst-fold and stability checks;
  - stored walk-forward schema in artifact.
- `app/ml/runtime.py`
  - exposed and validated the mandatory walk-forward schema.

### Tests

- added `tests/unit/test_walk_forward_validation_2026_07_05.py`;
- added gate regressions in `tests/unit/test_model_lifecycle.py`;
- extended runtime incompatibility parameterization in `tests/unit/test_quant_integrity_2026_07_02.py`;
- updated valid artifact/quality-gate fixtures in affected unit modules.

### Documentation/version

Updated `README.md`, `CHANGELOG.md`, `PATCH_1.11.0.md`, package version sources and all affected architecture/model/QA/compliance/traceability/operator/security/runbook documents.

No migration, public API or `.env` change was required.

## 7. Red → green evidence

Red command:

```text
python -m pytest -q tests/unit/test_walk_forward_validation_2026_07_05.py
```

Before implementation, pytest failed during collection:

```text
ImportError: cannot import name 'expanding_walk_forward_splits' from 'app.ml.training'
```

Green evidence:

- new module: 4 passed;
- targeted runtime/gate regression set: 16 passed;
- full suite: 476 passed, 4 skipped.

New independent assertions cover temporal order, label-end purge, horizon embargo, expanding train size, non-overlapping tests, insufficient history, final-holdout exclusion, actual fold model refits, instability rejection and tampered overlap rejection.

## 8. Compatibility, migrations and configuration

- Alembic: unchanged; no migration.
- API/UI: unchanged.
- `.env`: unchanged.
- Artifact contract: intentionally updated. Artifact 1.10.0 lacks `walk_forward_schema` and is rejected fail-closed.
- Required operator action: retrain candidate, inspect fold diagnostics, then repeat paper/shadow validation.
- Incumbent is not deactivated when training or gate fails.

## 9. Post-check

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Same external moviepy/Pillow host conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0 |
| `python -m ruff check .` | PASSED | Exit 0 |
| `python -m pytest -q` | PASSED | 476 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED | Exit 0 |
| `python -m pytest -q -rs tests/integration_postgres` | SKIPPED | 4 skipped: `TEST_DATABASE_URL` absent |
| `python manage.py doctor` | FAILED (environment) | Project `.venv` absent |

## 10. Not verified

- PostgreSQL migration/integration execution on a dedicated database.
- Native configured startup through `manage.py run`.
- Training duration and memory behaviour on the operator's full historical dataset.
- Real OOS profitability, paper/shadow performance or live manual execution quality.

## 11. Residual risks and limitations

- Three fixed folds are not nested CV, combinatorial purged CV or PBO.
- No hyperparameter search was added; therefore no claim of selection-bias correction is made.
- Fold policy stability currently uses positive point mean R; the final holdout retains the stricter phase-aware lower-confidence-bound gate.
- Historical bid/ask/depth, operator delay, event-by-event funding settlement, intrahorizon liquidation, broader market features and production drift remain open.
- Additional fold training increases trainer CPU time; it remains outside API and inference processes.

## 12. Rollback

1. Keep database unchanged; there is no schema migration to reverse.
2. Restore release 1.10.0 source and an artifact valid under its temporal schema.
3. Do not manually edit a 1.11.0 artifact to remove schema metadata.
4. Keep the 1.11.0 candidate and reports for audit even if it is not activated.

## 13. Recommended next work package

Implement historical funding replay tied to actual settlement timestamps: persist/validate point-in-time funding events, determine which settlements each hypothetical position crosses, apply direction-correct cash flows once, and test timezone/boundary cases. This is the next high-severity gap that can be implemented without pretending a historical orderbook dataset already exists.
