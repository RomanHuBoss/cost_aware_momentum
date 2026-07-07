# QA Report

Release: **1.38.0**

Date: **2026-07-07**
Scope: **background trainer preflight/fit symbol and temporal-scope alignment**

## Environment

- Python: 3.13.5.
- Project requirement: Python >=3.12.
- Input archive: `cost_aware_momentum-1.37.0-executable-spread-replay-alignment.zip`.
- Input SHA-256: `a6e9ce6dfa0b1c6615378d06e4e945513b4d80295cd4b13a3f5eefc9787de895`.
- Source version: 1.37.0.
- Alembic head before and after: `0017_model_artifact_blobs`.
- Baseline inventory: 102 production/script/web files, 102 test files, 15 documentation files and 17 migration revisions.
- Separate PostgreSQL integration database: not configured.

## Baseline before production changes

| Check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | FAILED: unrelated environment conflict — `moviepy 2.2.1` requires `pillow<12`, installed Pillow is 12.2.0 |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 744 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |

`python manage.py doctor` and `python manage.py test --require-integration` were not run because no operator configuration or isolated PostgreSQL test URL was available. The operator database was not accessed.

## Confirmed defects

### 1. Dynamic preflight and fit used different symbol cohorts — HIGH

`current_training_profile()` applied `AUTO_TRAIN_MAX_SYMBOLS` and persisted its exact replayed symbols. `run_training_once()` extracted those symbols only when `UNIVERSE_MODE=static`. In dynamic mode it passed `symbols=None` and `max_symbols=0`, reloading all symbols.

Expected: the scheduler authorizes and fits the same symbol cohort.

Actual: candidate fit could use symbols that were never present in the preflight profile, changing class distribution, policy density and temporal validation evidence.

### 2. Background fit was not frozen to the preflight data horizon — HIGH

The actual loader recalculated its upper bound from the newest database candle. Candles and universe snapshots committed after preflight could therefore enter the candidate while the stored trigger still described an older dataset.

Expected: a background training attempt is reproducible from its persisted trigger.

Actual: the dataset could advance between `due_reason()` and fit.

### 3. Quality gate did not revalidate actual fitted symbol coverage — MEDIUM

Preflight coverage was computed before full feature, market-context and label construction. `training_data_profile` on the candidate could include zero-row expected symbols, but the quality gate did not compare it with the preflight contract or enforce `AUTO_TRAIN_MIN_SYMBOL_COVERAGE_RATIO` at that stage.

## Red evidence

The final regression file was run against an untouched 1.37.0 tree:

```text
python -m pytest -q tests/unit/test_preflight_training_scope_alignment_2026_07_07.py
```

Result: **6 failed**:

- three failures because trigger-scope resolution did not exist;
- one failure because the market-data loader had no upper-bound contract;
- two failures because the quality gate accepted no expected preflight profile.

## Implemented correction

- Added a required, validated background trigger profile boundary.
- Exact preflight symbols are used in both static and dynamic modes.
- A second dynamic symbol selection is no longer performed during fit.
- Raw last/mark/index loading is bounded by `profile.end_time + horizon`.
- Candidate quality evidence records expected and actual profiles.
- Candidate promotion is fail-closed on symbol-scope drift, insufficient post-feature coverage or temporal advance beyond preflight.
- Existing manual/research calls remain compatible through optional parameters.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | FAILED: same unrelated `moviepy`/Pillow environment conflict as baseline |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| focused new regression suite | PASSED: 6 passed |
| focused trainer/lifecycle compatibility | PASSED: 33 passed |
| `python -m pytest -q` | PASSED: 750 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED: one head, `0017_model_artifact_blobs` |

No previously passing test regressed. The eight skipped tests are PostgreSQL integration contracts requiring an isolated database.

## Migration, configuration and compatibility

- New migration: none.
- New `.env` variable: none.
- Active model and runtime signal behavior are unchanged.
- A fresh background trigger is required after restart; existing active artifact may continue inference.
- The change can reduce candidate rows if the old fit had silently added symbols or later timestamps.
- All existing spread, quality, holdout, walk-forward, EV/RR, leverage and risk limits remain unchanged.

## Not run / residual limitations

- No real PostgreSQL background training attempt was executed.
- No operator database, Bybit account or live service was accessed.
- The preflight profile still measures replayed last-candle coverage before full context/label construction; the new post-fit gate catches loss, but a future optimization may add cheaper stage-by-stage attrition diagnostics before fitting.
- Historical dynamic membership before the prospective universe ledger remains unavailable.
- Exact orderbook depth, operator latency and actual fill PnL are not reconstructed.
- This correction does not prove economic edge or causally explain prior manual losses.
