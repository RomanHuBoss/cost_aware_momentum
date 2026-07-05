# Iteration Report — observed experiment-period support

Date: 2026-07-05
Release: 1.26.5

## 1. Input archive and baseline identity

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `533df587b4e8eb4ef84bf13c7fa3941aeaab9cb638ca169ae2f12fd878cea35d`
- Source version: 1.26.4
- Python requirement: >=3.12
- Source inventory before changes:
  - production Python files under `app/`: 73;
  - test files: 82;
  - documentation files under `docs/`: 7;
  - Alembic migrations: 14.
- Source Alembic head: `0014_ui_exposure_ledger`.
- No production `.env`, credential file, database dump, cache, virtual environment or real model artifact was present in the input archive.

## 2. Objective and acceptance criteria

Objective:

> After this iteration, experiment-selection inference must use only hourly periods covered by actually observed decision cohorts and their valid label horizons; missing calendar gaps must not become synthetic zero returns, and legacy contaminated evidence must fail closed.

Acceptance criteria:

1. Two observed 1-hour decision windows 100 hours apart produce four covered periods, not 102 calendar rows.
2. Genuine zero-return decision/holding periods within covered windows remain represented.
3. Evidence exposes observed-opportunity, covered and omitted-gap counts.
4. Count/timestamp arithmetic is validated before PBO/DSR analysis.
5. Legacy v1 period evidence cannot be reused for normal promotion.
6. Invalid evidence returns a diagnostic failed promotion gate instead of an unhandled exception.
7. Risk, cost, model-quality, artifact and advisory-only invariants remain unchanged.
8. Full available suite remains green.

## 3. Sources read and affected data flow

Reviewed before modification:

- current user request and iterative master prompt;
- `README.md`, `CHANGELOG.md`, `PATCH_1.26.2.md`–`PATCH_1.26.4.md`;
- `pyproject.toml`, `.env.example`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- three previous iteration reports;
- DOCX specification section 10, especially paragraphs on final holdout, event-driven backtest, portfolio metrics and PBO/DSR;
- `scripts/backtest.py`;
- `app/research/overfitting.py`, `app/research/dependence.py`;
- `app/services/experiment_ledger.py`, `app/services/model_promotion.py`;
- related econometric, backtest, promotion and lifecycle tests.

Affected flow:

```text
validated holdout directional rows
  -> one selected direction per symbol/hour
  -> observed decision-to-horizon support union
  -> capital-sleeve exit PnL on covered hourly index
  -> immutable SUCCEEDED experiment evidence + counts + schema v2
  -> ledger validation
  -> aligned trial matrix
  -> PBO / DSR / dependence report
  -> fail-closed normal model-promotion gate
```

## 4. Baseline before changes

Host/global environment:

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED | unrelated global MoviePy/Pillow conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no compile errors |
| `python -m ruff check .` | UNAVAILABLE | `ruff` not installed |
| `python -m pytest -q` | FAILED | 33 collection errors because `psycopg` absent |
| `node --check web/js/app.js` | PASSED | syntax valid |

Comparable isolated baseline in `/mnt/data/cam_iter_venv`:

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no compile errors |
| `python -m ruff check .` | PASSED | no findings |
| `python -m pytest -q` | PASSED | 615 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |

No production source was changed before these baselines were recorded.

## 5. Confirmed defect

### DEFECT-1 — unavailable calendar gaps entered experiment inference as zero returns

- Classification: **CONFIRMED DEFECT**
- Severity: **critical**
- Area: econometrics / model-promotion governance
- Files:
  - `scripts/backtest.py::policy_backtest`;
  - `_simulate_capital_sleeves_evidence` consumer path;
  - `app/services/experiment_ledger.py::_trial_evidence_from_success`;
  - `app/services/model_promotion.py::evaluate_experiment_promotion_gate`.

Before 1.26.5:

```text
period_start = min(decision_time)
period_end = max(exit_time)
period_grid = date_range(period_start, period_end, hourly)
```

A deterministic reproduction with observed decisions at `2025-01-01 00:00Z` and `2025-01-05 04:00Z`, horizon 1 hour, produced 102 experiment periods. Only four timestamps were covered by valid decision-to-horizon windows; 98 unavailable hours were silently added as zero returns.

Expected behavior: zero return is valid only for a genuine observed no-trade/holding period inside known support.
Actual behavior: unavailable time was indistinguishable from an observed zero return.

Impact:

- `minimum_periods` could be satisfied by data absence;
- sample volatility and Sharpe could be altered;
- DSR effective evidence, PBO segmentation and dependence blocks could be distorted;
- a contaminated experiment family could participate in normal activation.

Why tests missed it: the existing helper test supplied an already continuous grid and verified zero rows within that grid. It did not test how production constructed the grid from disjoint observed cohorts, and no schema check distinguished synthetic-calendar v1 evidence.

## 6. Plan and actual diff

### Production

- `scripts/backtest.py`
  - added `_observed_policy_period_grid`;
  - replaced min-to-max calendar fill with union of decision-to-horizon windows;
  - persisted coverage counts and v2 schema in report/ledger evidence.
- `app/research/overfitting.py`
  - added canonical experiment period-return schema v2 constant.
- `app/services/experiment_ledger.py`
  - requires exact v2 schema;
  - validates non-negative counts, chronology, uniqueness, covered length and omitted-gap arithmetic.
- `app/services/model_promotion.py`
  - converts invalid ledger evidence into `invalid_experiment_return_evidence` failed gate.
- `app/__init__.py`, `pyproject.toml`
  - version 1.26.5.

### Tests

- added `tests/unit/test_experiment_observed_period_path_2026_07_05.py` with three independent regression tests.

### Documentation

- `README.md`;
- `CHANGELOG.md`;
- `PATCH_1.26.5.md`;
- `docs/SPEC_COMPLIANCE.md`;
- `docs/TRACEABILITY.md`;
- `docs/QA_REPORT.md`;
- this report.

### Not changed

- database schema/migrations;
- public HTTP API;
- `.env` configuration;
- trading/risk thresholds;
- model classes/features/calibration;
- Bybit client or advisory-only boundary.

## 7. Red → green evidence

Command:

```text
python -m pytest -q tests/unit/test_experiment_observed_period_path_2026_07_05.py
```

Before implementation:

```text
3 failed
- 102 timestamps emitted instead of four covered timestamps
- legacy v1 evidence did not raise
- promotion gate propagated ValueError
```

After implementation:

```text
3 passed
```

The numerical regression independently verifies two observed windows, four covered periods and 98 omitted unavailable calendar periods.

## 8. Migration, API, configuration and compatibility

- Alembic migration: none.
- Alembic head: `0014_ui_exposure_ledger`.
- Public HTTP API: unchanged.
- `.env`: no additions or changes.
- Period evidence schema: v1 → `observed-opportunity-covered-hourly-capital-return-path-v2`.
- Active models are not deactivated.
- Existing experiment families with successful v1 evidence cannot authorize normal promotion; rerun their preregistered backtests under 1.26.5.
- Append-only historical ledger rows are not rewritten.

## 9. Post-change verification

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no compile errors |
| `python -m ruff check .` | PASSED | no findings |
| `python -m pytest -q` | PASSED | 618 passed, 4 skipped, 61 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |
| version consistency | PASSED | package and application are 1.26.5 |
| static migration head | PASSED | one head: `0014_ui_exposure_ledger` |
| release integrity / ZIP re-extraction | PASSED | 220 files checked; 220 manifest entries; one root directory; clean `unzip -t`; re-extracted tree verified |

## 10. Not verified and why

- PostgreSQL integration/concurrency tests: NOT RUN because no isolated `TEST_DATABASE_URL` or `POSTGRES_ADMIN_URL` is configured.
- `manage.py doctor`: executed and FAILED on environment readiness only: `.env` absent, default secrets unresolved, `psql`/`pg_dump`/`pg_restore` absent and PostgreSQL unreachable.
- Live/forward profitability and signal frequency: require market time and operator evidence; unit tests cannot establish them.
- Exact historical bid/ask/orderbook, operator latency and exchange liquidation mechanics remain unavailable.

## 11. Residual risks and limitations

1. The return path recognizes PnL at modeled exits; it is not an hourly mark-to-market equity curve.
2. Excluding unsupported gaps prevents false observations but can reduce period count and make more experiment families `BLOCKED`; this is intended fail-closed behavior.
3. Existing append-only v1 ledger events remain for audit but require new v2 trials.
4. The patch does not prove edge or justify lowering policy/model gates.

## 12. Rollback procedure

1. Stop API/worker/trainer processes.
2. Restore the 1.26.4 application files; no database downgrade is required.
3. Do not rewrite experiment ledger rows.
4. Be aware that rollback re-enables v1 evidence and the synthetic-calendar defect; normal promotion should remain disabled until returning to 1.26.5 or later.

## 13. Recommended next work package

Implement an exit-realized versus hourly mark-to-market experiment-path comparison using only point-in-time mark data already required by the label pipeline, with preregistered choice of the primary return convention. This should be a separate iteration because it changes econometric semantics beyond correcting unsupported calendar gaps.
