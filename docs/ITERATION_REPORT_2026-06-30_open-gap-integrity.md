# Iteration report — open-gap integrity

Date: 2026-06-30
Target version: 1.8.12
Scope: open-first barrier path and realized stop-gap accounting

## 1. Input archive and baseline identity

- Input archive: `cost_aware_momentum-main(1).zip`.
- Input SHA-256: `1ce5c3bcd756d7a556230c426b15d1c93fa27036c1df3c406e3e8e50b67af535`.
- Input application/package version: `1.8.11`.
- Python requirement: `>=3.12`.
- Alembic head before and after the iteration: `0006_manual_trade_remaining_risk`.
- Production Python files under `app/` and `scripts/`: 68.
- Test Python files after adding the regression module: 33.
- Markdown/DOCX files under `docs/` before this report: 18.
- Alembic revisions: 6.
- The input archive contained no production `.env`, virtual environment, cache directory, bytecode, database dump, or real model artifact.

The supplied statement that external reviewers had found 17 critical and 9 medium defects did not include locations, reproductions, or evidence. Those counts are therefore not treated as established facts. This iteration independently proves one coherent correctness package with eight red regression cases; none is relabelled as critical without evidence of a direct safety or data-loss path.

## 2. Iteration objective and acceptance criteria

Objective:

> After this iteration, labels, counterfactual outcomes, holdout promotion metrics, research backtests, and plan outcomes must apply one open-first OHLC barrier contract and must not charge a modeled stop-gap reserve twice after an adverse gap has already been realized in the exit price.

Acceptance criteria:

1. Barrier windows require valid finite positive `open/high/low/close` and reject `open` or `close` outside `[low, high]`.
2. The candle open is resolved before unordered intrabar high/low extrema for both LONG and SHORT geometry.
3. An adverse opening gap through SL is valued at the observed open; a favorable TP gap is conservatively capped at the modeled target.
4. Opening exits preserve exact event time instead of being shifted to candle close.
5. Holdout policy metrics use realized gross return and actual exit-notional fee rather than replacing every SL with planned stress loss.
6. Backtest and PlanOutcome charge only the residual stop-gap reserve not already embedded in an observed adverse exit.
7. New artifacts and policy/outcome payloads carry explicit incompatible schema/version identifiers so legacy metrics cannot be silently compared.
8. The focused regression module and the complete available suite pass without reopening prior tests.

## 3. Sources read and affected data flow

Repository context reviewed before the change:

- `README.md`, `CHANGELOG.md`, `PATCH_1.8.10.md`, `PATCH_1.8.11.md`;
- `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/OPERATOR_MANUAL.md`;
- relevant production modules and unit/integration test structure;
- `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`, especially the sections stating that hourly OHLC does not order TP/SL touches, stop price does not guarantee fill during a gap, and actual PnL must use actual entry/exit prices.

`docs/INCIDENT_RUNBOOK.md` does not exist in the supplied archive and was not invented.

Affected research flow:

`confirmed Candle OHLC -> feature/label builder -> triple-barrier result -> dataset metadata and temporal split -> policy metrics -> lifecycle promotion gate -> research backtest/report`

Affected post-event flow:

`confirmed Candle OHLC -> barrier outcome service -> SignalOutcome -> PlanOutcome valuation -> database/API/audit payload`

## 4. Reproducible baseline before source changes

A first attempt in the host Python environment was not usable as a project baseline: collection stopped with 17 import errors because `psycopg` was absent, Ruff was absent, and the host `pip check` contained an unrelated global `moviepy`/`pillow` conflict. No source change was made based on those environmental failures.

A clean isolated environment was then created outside the repository and the project was installed with `.[dev]`.

| Command | Baseline result on unmodified 1.8.11 |
|---|---|
| `python --version` | `Python 3.13.5` |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | `264 passed, 4 skipped, 19 warnings in 4.50s` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | `0006_manual_trade_remaining_risk (head)` |
| `python manage.py doctor` | NOT RUN — no runtime `.env` or safe PostgreSQL configuration |
| `python manage.py test --require-integration` | NOT RUN — no isolated `TEST_DATABASE_URL` |

The four skips are PostgreSQL integration tests that explicitly require `TEST_DATABASE_URL`.

## 5. Confirmed defects and evidence

### 5.1 HIGH — opening price omitted from barrier path

- Files: `app/ml/labels.py::triple_barrier_outcome`, `app/services/outcomes.py::evaluate_barrier_outcome`.
- Actual behavior: only high/low/close were evaluated. A favorable opening gap beyond TP followed by a same-bar SL touch was classified as SL; an adverse opening gap through SL was valued at the stop, not the observable open.
- Expected behavior: open is the first ordered observation in the bar. It must be resolved before unordered high/low; stop loss cannot guarantee its trigger price through a gap.
- Impact: target corruption, censored tail loss, mismatch between training labels and post-event PnL.
- Why prior tests missed it: fixtures did not carry or assert open-first gap semantics.
- Evidence: focused tests 1, 2, and 4 failed on unmodified 1.8.11.

### 5.2 HIGH — promotion metrics replaced realized SL with planned stress loss

- File: `app/ml/training.py::evaluate_policy_model`.
- Actual behavior: every SL contribution was set to `-stress_downside_rate`, even when `realized_gross_return` showed a worse opening gap.
- Expected behavior: promotion evidence must use the realized exit return and fee on actual exit notional; planned stress downside remains the denominator/risk budget, not an override of realized PnL.
- Impact: materially optimistic holdout R, drawdown, and promotion evidence in gap-loss cases.
- Why prior tests missed it: existing SL fixtures exited at the modeled barrier.
- Evidence: focused test 6 expected `-4/3 R`; unmodified code returned `-1 R`.

### 5.3 MEDIUM — invalid OHLC open was accepted

- File: `app/ml/labels.py::triple_barrier_outcome`; the same invariant was absent from `OutcomeBar` evaluation.
- Actual behavior: `open > high` or `open < low` could enter label/outcome calculations.
- Expected behavior: positive finite `low <= open/close <= high`.
- Impact: corrupt upstream market data could generate deterministic but false labels/outcomes instead of failing closed.
- Evidence: focused test 3 did not raise on unmodified 1.8.11.

### 5.4 MEDIUM — opening exit time shifted to candle close

- File: `app/ml/training.py::validate_policy_evaluation_metadata`.
- Actual behavior: `exit_time = decision_time + (exit_index + 1) hours` for every outcome, including an exit at the first future candle open.
- Expected behavior: opening exits use the bar open time; non-opening exits keep the conservative bar-close timestamp.
- Impact: incorrect event-time ordering and distorted exit-time aggregation/drawdown timing.
- Evidence: focused test 5 expected 12:00 UTC; unmodified code produced 13:00 UTC.

### 5.5 MEDIUM — realized gap and full gap reserve were both charged

- Files: `scripts/backtest.py::policy_backtest`, `app/services/outcomes.py::estimate_plan_outcome`.
- Actual behavior: the observed adverse gap was already present in `realized_gross_return`/exit price, then the full planned reserve was subtracted again.
- Expected behavior: before execution, the full reserve remains in planned downside; after an actual exit is known, charge only `max(configured reserve - observed gap beyond stop, 0)`.
- Impact: biased realized research returns and counterfactual PlanOutcome PnL; strategy comparisons become internally inconsistent.
- Evidence: focused tests 7 and 8 failed on unmodified 1.8.11.

## 6. Change plan and actual diff

### Production

- `app/ml/labels.py`
  - adds full OHLC validation;
  - resolves open first;
  - stores `exit_at_open`;
  - uses observed adverse gap fill and capped favorable TP fill.
- `app/services/outcomes.py`
  - adds `OutcomeBar.open` and open-first evaluation;
  - bumps outcome contract to `primary-barrier-intrabar-open-gap-v4`;
  - values residual reserve using the plan stop and observed exit.
- `app/ml/training.py`
  - persists `exit_at_open` and label-path schema;
  - reconstructs exact modeled exit time;
  - values realized outcomes with actual exit return/fee and residual reserve;
  - publishes policy schema `exit-time-realized-gap-horizon-sleeves-v3`.
- `app/ml/lifecycle.py`
  - stores `label_path_schema_version=ohlc-open-first-stop-gap-v1`;
  - requires policy schema v3 in the promotion gate.
- `scripts/backtest.py`
  - removes duplicate gap-reserve charge from realized and stressed results;
  - exposes `stop_gap_reserve_accounting=residual_after_realized_gap_v1`.
- `app/__init__.py`, `pyproject.toml`
  - version `1.8.12`.

### Tests

- Added `tests/unit/test_barrier_open_gap_integrity.py` with eight independent assertions.
- Updated existing OutcomeBar/label fixtures and lifecycle schema expectations in:
  - `tests/unit/test_counterfactual_outcomes.py`;
  - `tests/unit/test_intrabar_outcomes.py`;
  - `tests/unit/test_labels_features.py`;
  - `tests/unit/test_model_artifact_recovery.py`;
  - `tests/unit/test_model_lifecycle.py`;
  - `tests/unit/test_quant_correctness_hardening.py`;
  - `tests/unit/test_quant_econometric_audit_2026_06_29.py`;
  - `tests/unit/test_quant_integrity_2026_06_29.py`.

### Documentation

- `README.md`, `CHANGELOG.md`, `PATCH_1.8.12.md`;
- `docs/ARCHITECTURE.md`, `docs/MODEL_CARD.md`, `docs/QA_REPORT.md`;
- `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- this report.

No database migration, API endpoint, environment variable, dependency, or advisory/execution boundary was changed.

## 7. Red -> green evidence

Command run against the unmodified 1.8.11 baseline after copying only the new regression test:

```bash
python -m pytest -q tests/unit/test_barrier_open_gap_integrity.py
```

Red result:

```text
8 failed in 2.70s
```

Failures independently covered:

1. favorable opening gap ordered after same-bar extrema;
2. adverse opening gap capped at stop;
3. invalid open outside OHLC accepted;
4. OutcomeBar lacked open semantics;
5. opening exit time shifted one hour;
6. realized gap loss capped at planned `-1 R`;
7. backtest double-charged reserve;
8. PlanOutcome lacked stop-aware residual reserve.

Green result after the fix:

```text
8 passed in 2.59s
```

Complete suite after correction:

```text
272 passed, 4 skipped, 19 warnings in 4.59s
```

## 8. Migration, API, configuration, and compatibility

- Alembic: no new revision; head remains `0006_manual_trade_remaining_risk`.
- `.env`: no new or changed variable.
- Public HTTP API: no endpoint/schema change was introduced by this package.
- Bybit client: no order placement, amendment, cancellation, or write endpoint was added.
- Existing runtime model artifacts remain feature/class compatible.
- Candidate/incumbent policy metrics produced under schema v2 are intentionally not eligible for silent comparison with v3.
- New training artifacts should be produced and holdout/backtest metrics recalculated before promotion comparison.
- New post-event evaluations use outcome version v4; historical outcome rows are not rewritten automatically.

## 9. Final post-change verification

The final release checks are recorded here after documentation and manifest regeneration:

| Command | Result |
|---|---|
| `python -m pip check` | PASSED — `No broken requirements found.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED — `All checks passed!` |
| `python -m pytest -q` | `272 passed, 4 skipped, 19 warnings in 4.74s` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | `0006_manual_trade_remaining_risk (head)` |
| whitespace/source hygiene scan | PASSED on all changed text files; no trailing whitespace or missing final newline |
| write-method/secret/release-junk scan | PASSED — no Bybit write-method/order endpoint match and no private-key/token pattern |
| `python manage.py release-check` | PASSED — 147 files checked, 147 manifest entries |

No previously green available test regressed.

## 10. Checks not performed

- PostgreSQL integration tests and migration upgrade/downgrade were NOT RUN because no isolated `TEST_DATABASE_URL` was available.
- `python manage.py doctor` was NOT RUN because the clean audit environment had no runtime `.env` or safe PostgreSQL target.
- No live, paper, shadow, or forward market run was performed.
- No profitability claim is made.

## 11. Residual risks and limitations

1. After the candle open, hourly high/low still cannot order TP and SL touches. Complete lower-timeframe history is required; otherwise the existing conservative ambiguity rule remains.
2. Stop-gap reserve is a configurable stress assumption, not a forecast of the exact future fill distribution.
3. Research still lacks full historical order-book/no-fill/partial-fill/operator-latency simulation and intrahorizon mark-to-market.
4. Historical outcome rows and legacy policy/backtest payloads are versioned rather than silently rewritten.
5. PostgreSQL concurrency, migrations, and database persistence were not exercised in this environment.
6. Technical consistency does not establish economic edge or future profitability.

## 12. Rollback procedure

1. Stop API, inference worker, and trainer processes.
2. Restore the 1.8.11 source archive; no database downgrade is required.
3. Keep v3 policy metrics and v4 outcomes out of 1.8.11 automatic comparisons; they use newer semantics.
4. Re-evaluate any candidate/incumbent pair under one common version before manual activation.
5. Restart processes and run the 1.8.11 release checks.

## 13. Recommended next work package

Implement a point-in-time historical funding timeline shared by holdout/backtest valuation and manual filled-position revaluation. The next iteration should prove settlement-boundary inclusion, sign, interval changes, and missing-history fail-closed behavior without adding execution capability.
