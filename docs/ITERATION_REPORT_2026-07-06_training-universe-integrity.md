# Iteration report — training universe integrity

Date: 2026-07-06  
Target release: 1.28.2  
Scope: point-in-time and stable symbol cohort for model training

## 1. Input archive and identification

- Input: `cost_aware_momentum-main.zip`.
- SHA-256: `8552ca31c0879d8556754f92f34b58506e1ae2865e0cb96424124e79e7919ec4`.
- Source version: 1.28.1 in `pyproject.toml` and `app/__init__.py`.
- Python requirement: >=3.12; checks used Python 3.13.5.
- Input inventory: 234 files; 93 Python files under `app/` and `scripts/`, plus `manage.py`; 86 test Python files; 12 files under `docs/` plus README; 14 migration revisions.
- Alembic head: `0014_ui_exposure_ledger`.
- Input archive contained a release manifest and no `.env`, embedded virtualenv, cache, bytecode, real model artifact or database dump.

## 2. Iteration goal and acceptance criteria

Goal:

> After this iteration, a capped dynamic training cohort must be selected only from label-eligible confirmed historical candles and must remain identical from preflight profile through model fit, without weakening any quality or promotion gate.

Acceptance criteria:

1. Latest ticker turnover is not consulted by dynamic historical training selection.
2. Candidate rows used for cohort eligibility end no later than `latest confirmed candle - horizon`.
3. Each selected symbol has at least the configured minimum number of eligible bars and reaches the label cutoff.
4. Selection ordering is deterministic.
5. An explicit empty selection fails closed rather than expanding to all symbols.
6. Background fit uses exact symbols from the trigger training-data profile.
7. Manual and background loaders receive the same horizon/minimum-history contract.
8. Existing tests and fail-closed gates remain green.

## 3. Sources read and data flow

Read:

- `README.md`, `CHANGELOG.md`, `pyproject.toml`, `.env.example`;
- `PATCH_1.27.0.md`, `PATCH_1.28.0.md`, `PATCH_1.28.1.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md` and recent iteration reports;
- `app/config.py`, `app/ml/lifecycle.py`, `app/ml/data_profile.py`, `app/ml/training.py`;
- `app/workers/trainer.py`, `app/services/universe.py`, relevant ORM models;
- manual training entry point and related unit tests.

The generic master prompt named `docs/ARCHITECTURE.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md` and `OPERATOR_MANUAL.md`; these files were absent from the supplied archive.

Relevant flow before the patch:

```text
latest ticker snapshots
  -> rank by current turnover_24h
  -> select up to AUTO_TRAIN_MAX_SYMBOLS
  -> query historical candles for those current symbols
  -> preflight TrainingDataProfile
  -> later re-rank latest tickers
  -> load possibly different symbol cohort
  -> build candidate / temporal validation / quality gate
```

Relevant flow after the patch:

```text
latest confirmed hourly candle
  -> label cutoff = latest - horizon
  -> eligible confirmed candle rows inside lookback and <= cutoff
  -> minimum rows + reach-to-cutoff filter
  -> deterministic cohort
  -> persisted preflight TrainingDataProfile.symbols
  -> exact explicit cohort reused for load and fit
  -> unchanged temporal validation / quality gate / governed promotion
```

## 4. Baseline

A clean project-local virtual environment was used because the host Python initially lacked project dependencies and had an unrelated global Pillow/MoviePy conflict.

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements in isolated venv |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no compile errors |
| `python -m ruff check .` | PASSED | no violations |
| `python -m pytest -q` | PASSED | 644 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |
| `python manage.py doctor` | FAILED | environment: `.env`, secrets, PostgreSQL tools/server absent |
| `python manage.py test --require-integration` | NOT RUN | no `POSTGRES_ADMIN_URL` or `TEST_DATABASE_URL` |

## 5. Confirmed defects/gaps

### TU-01 — ex-post ticker ranking defines historical cohort

- Classification: **CONFIRMED DEFECT**.
- Severity: **high** econometric/model-governance risk.
- Location: `app/ml/lifecycle.py::_select_training_symbols`.
- Baseline behavior: select each symbol's newest ticker, rank by `turnover_24h`, and apply that current list to all historical rows.
- Expected behavior: cohort evidence must be available by the label cutoff and must meet training-history requirements.
- Impact:
  - post-cutoff/ex-post asset selection can contaminate historical holdout interpretation;
  - a newly hot contract can displace a mature contract while lacking minimum history;
  - coverage gate can fail due to cohort construction rather than actual absence of a viable mature cohort.
- Why tests missed it: existing data-profile tests validated counts after selection but did not test the information set used to select symbols.

Red reproduction:

```text
python -m pytest -q tests/unit/test_training_universe_integrity_2026_07_06.py
1 failed
actual ['HOT_NEW_USDT']; expected ['BTCUSDT', 'ETHUSDT']
```

### TU-02 — preflight/fit dynamic-universe TOCTOU

- Classification: **CONFIRMED DEFECT** by deterministic data-flow analysis.
- Severity: **high** evidence-integrity/operational risk.
- Location: `app/workers/trainer.py::run_training_once`.
- Baseline behavior: preflight persisted `training_data_profile`, then fit independently resolved latest ticker ranking again.
- Expected behavior: candidate data must correspond to the exact profile that authorized the training attempt.
- Impact: a moving turnover ranking could make the actual fitted symbol set differ from trigger evidence and cause non-reproducible coverage/gate outcomes.
- Why tests missed it: trainer tests covered scheduling and gates but did not assert cohort identity across the preflight-to-fit boundary.

### Related observed limitation — one day cannot satisfy default gates

This is not a defect and was not changed. Defaults require at least 1206 unique hourly timestamps before bootstrap quality evaluation. Approximately 24 timestamps after one day are mathematically insufficient. Lowering this boundary would weaken temporal/holdout evidence and was explicitly avoided.

## 6. Plan and actual diff

Production:

- `app/ml/lifecycle.py`
  - remove ticker-based training ranking;
  - add label-cutoff/coverage-based deterministic selection;
  - distinguish unrestricted `None` from explicit empty list;
  - pass horizon and minimum-history contract through loaders.
- `app/workers/trainer.py`
  - pin exact preflight profile symbols through data loading and fit.
- `scripts/train.py`
  - use the same horizon/minimum-history selection contract.

Tests:

- `tests/unit/test_training_universe_integrity_2026_07_06.py`.

Version/release/docs:

- `pyproject.toml`, `app/__init__.py`;
- `README.md`, `CHANGELOG.md`, `PATCH_1.28.2.md`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this report and regenerated `SHA256SUMS`.

Migration/config/API:

- no migration;
- no `.env` variable/default change;
- no public API change;
- no artifact-schema or feature-schema change.

## 7. Red → green evidence

Test: `test_dynamic_training_universe_uses_label_eligible_candle_history_not_latest_ticker`.

Red on source 1.28.1:

```text
1 failed
assert ['HOT_NEW_USDT'] == ['BTCUSDT', 'ETHUSDT']
```

The synthetic session exposed both possible information sources: latest ticker ranking returned a newly hot symbol; the label-eligible candle query returned two mature symbols. Baseline used the former.

Green after implementation:

```text
1 passed
```

The test additionally asserts that:

- no `ticker_snapshots` relation appears in selection SQL;
- lower and upper time bounds are present;
- minimum row count is enforced;
- latest eligible candle reaches the cutoff;
- the 300-row threshold and eight-hour label cutoff are bound parameters.

## 8. Compatibility and rollback

Compatibility:

- active artifacts remain runnable;
- existing model registry rows are unchanged;
- new candidates are trained on a corrected cohort-selection contract;
- all gates and recommendation thresholds are unchanged.

Rollback:

1. Stop trainer and worker processes.
2. Restore the 1.28.1 source tree.
3. No database downgrade or `.env` rollback is required.
4. Restart processes.
5. Do not delete audit/model evidence. Any candidate trained under 1.28.2 can remain inactive or be reviewed explicitly; normal promotion evidence remains governed by existing gates.

## 9. Post-check

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no compile errors |
| `python -m ruff check .` | PASSED | no violations |
| targeted regression | PASSED | 1 passed |
| related trainer/lifecycle tests | PASSED | 24 passed |
| `python -m pytest -q` | PASSED | 645 passed, 4 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |
| `python -m alembic heads` | PASSED | `0014_ui_exposure_ledger` single head |
| release manifest | PASSED | 236 eligible files match 236 entries |
| ZIP test/re-extraction | PASSED | one root, clean compressed data, re-extracted manifest verified |

## 10. Not verified

- PostgreSQL integration and query-plan performance on a large candle table.
- Native Windows run.
- Real Bybit data replay and forward paper evidence after retraining.
- Historical live-universe membership and point-in-time spread/turnover eligibility before local storage began.
- Causal attribution of the user's past losses.

## 11. Residual risks and limitations

- Coverage-based cohort selection is an honest data-availability cohort, not a reconstruction of the exact historical production universe.
- `AUTO_TRAIN_MAX_SYMBOLS=0` intentionally means unrestricted loading and therefore bypasses capped cohort ranking.
- The trainer still requires a governed experiment family for normal automatic promotion; it does not auto-create preregistration/backtests.
- Exact historical bid/ask/depth, operator latency, funding forecasts and full exchange liquidation mechanics remain partial/absent as documented in `SPEC_COMPLIANCE.md`.
- Technical correctness does not establish economic edge or profitability.

## 12. Recommended next work package

Implement a prospective, append-only historical universe-eligibility ledger that records each symbol's instrument status, age, spread and turnover decision at every universe refresh. Training/backtest can then reconstruct the exact production-eligible cross-section point-in-time instead of using candle-coverage membership. This should be a separate migration-backed iteration with PostgreSQL integration tests.
