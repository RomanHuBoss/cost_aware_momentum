# Iteration report — quant policy integrity — 2026-06-30

## 1. Input

- Archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `2bd4bf1e5a327e3f642bb56756a65d6de6055e2e9db36e9e16e6bc32a94e0641`
- Source version: `1.8.13`
- Python requirement: `>=3.12`
- Alembic revisions: 6; head `0006_manual_trade_remaining_risk`
- Source inventory before edits: 68 production/source assets under `app` and `scripts`, 33 original Python test files plus this iteration's red test, 20 existing documentation files, 6 migrations.
- Input archive contained no `.env`, secret, virtual environment, cache, bytecode, dump, real model artifact or nested release archive.

## 2. Goal and acceptance criteria

After this iteration, recommendation economics, model promotion evidence and execution-plan lifecycle must fail closed when settlement timing, independent temporal evidence or plan ownership is not proven.

Acceptance criteria:

1. Favorable projected funding cannot improve pre-trade RR/EV or direction selection without a known exit crossing settlement.
2. Policy mean R/EV is equal-weight by hourly decision cohort; symbol count cannot reweight time.
3. Auto-activation requires the configured minimum number of independent hourly cohorts as well as trades.
4. Accepted/entered/partial/closed plans cannot be duplicated through recalculation.
5. Concurrent plan version allocation is serialized in PostgreSQL.
6. Default horizon is positive and included in the configured horizon set.
7. Existing tests remain green and release boundaries remain advisory-only/PostgreSQL-only.

## 3. Sources and data flow

Read: `README.md`, `CHANGELOG.md`, patches 1.8.10–1.8.13, `pyproject.toml`, `.env.example`, architecture/QA/compliance/traceability/model/config/security/operator/runbook documentation, risk math, signal publication, execution-plan service, recommendation API, ML training/lifecycle, backtest and relevant tests.

Flows reviewed:

- ticker funding/spec → projected scenario → Decimal RR/EV → signal direction → execution plan → API/UI;
- holdout rows/probabilities → direction policy → trade/cohort contributions → quality gate → candidate activation;
- signal/profile → latest plan → version allocation → plan persistence → accept/recalculate lifecycle.

External semantics were checked against official Bybit documentation dated May/June 2026 (funding is paid/received only when the position is held at the exact funding time; intervals vary by instrument) and PostgreSQL documentation for transaction-scoped advisory locks.

## 4. Baseline

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | FAILED — host-level `moviepy 2.2.1` requires `pillow<12`, host has `pillow 12.2.0`; unrelated to project dependency graph |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `ruff check .` | PASSED using isolated Ruff 0.15.20 |
| `python -m pytest -q` | PASSED — 276 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0006_manual_trade_remaining_risk` |
| `python manage.py release-check` | PASSED on a fresh extraction — 149/149; the separate local working tree later failed only after baseline commands generated forbidden caches/egg-info |
| `python manage.py doctor` | NOT RUN successfully — native project `.venv` absent |
| `python manage.py test --require-integration` | NOT RUN successfully — native `.venv` and safe `TEST_DATABASE_URL` absent |

## 5. Confirmed defects

### D1 — favorable funding credited without proven holding period — CRITICAL

- Files/functions: `app/risk/math.py::upside_rate`, `net_rr_and_ev`; `scripts/backtest.py::policy_backtest`; consumers in signal and plan construction.
- Reproduction: positive funding and a SHORT scenario increased upside from 0.04 to 0.05 and EV/R from 0.68 to 1.18 although no TP/SL exit timestamp proved that settlement was crossed.
- Expected: only funding settlements crossed while the position is open may be paid/received. Before exit timing is known, adverse funding may be reserved, but favorable funding cannot be guaranteed.
- Impact: false direction preference, inflated RR/EV, false NO-TRADE→TRADE transition and optimistic backtests.
- Existing tests encoded the incorrect oracle that favorable funding must always be credited.

### D2 — cross-sectional pseudo-replication in promotion means — CRITICAL

- File/function: `app/ml/training.py::evaluate_policy_model`.
- Reproduction: one +1R hourly cohort followed by a cohort of nine -0.2R symbols produced raw trade mean -0.08R; the portfolio-consistent equal-hour mean is +0.4R.
- Impact: changing universe breadth at one timestamp changes promotion statistics without adding temporal evidence.
- Existing sleeve weighting protected total R but not mean R/EV and win-rate semantics.

### D3 — trade count could substitute for independent time evidence — CRITICAL

- File/function: `app/ml/lifecycle.py::evaluate_quality_gate`.
- Reproduction: 100 actionable symbols from one timestamp passed the `AUTO_TRAIN_MIN_POLICY_TRADES=20` evidence threshold.
- Impact: auto-activation can be approved from one market hour/regime.
- Existing schema had no `policy_cohorts` field.

### D4 — recalculation could duplicate immutable plans — HIGH

- Files/functions: `app/services/execution.py::recalculate_all_active_signals`; `app/api/v1/recommendations.py::{accept_recommendation,recalculate_plan}`.
- Reproduction: an `ACCEPTED` plan was left unchanged but a new plan was still created; `PARTIAL` was not protected consistently.
- Impact: parallel plan ownership, duplicate risk reservation, ambiguous UI/operator state.
- Existing tests did not cover recalculation over live/terminal states.

### D5 — non-atomic plan version allocation — HIGH

- File/function: `app/services/execution.py::create_execution_plan`.
- Reproduction: `max(version)+1` was read before any per-signal/profile lock. Concurrent transactions could select the same version and fail at flush or race lifecycle updates.
- Impact: intermittent plan creation failure and non-idempotent operator workflow under concurrency.
- Existing acceptance risk lock covered portfolio totals, not plan version allocation.

### D6 — invalid default horizon accepted — MEDIUM

- File/function: `app/config.py::validate_cross_field_policy`.
- Reproduction: `DEFAULT_HORIZON_HOURS=0` or `12` with `HORIZONS_HOURS=[4,8]` instantiated successfully.
- Impact: later artifact/policy mismatch and invalid funding/barrier horizon paths.
- Existing validation checked only the list, not the selected default.

## 6. Changes

Production:

- `app/risk/math.py`: introduced adverse-only pre-trade funding recognition while retaining signed realized funding cash flow.
- `scripts/backtest.py`: static funding without settlement timestamps is adverse-only.
- `app/ml/training.py`: v5 cohort-weighted mean metrics, `policy_cohorts`, net exit-event profit factor and trade diagnostics.
- `app/ml/lifecycle.py`: required independent cohort minimum and v5 candidate/incumbent compatibility.
- `app/services/execution.py`: immutable plan states, bulk skip and per-signal/profile transaction advisory lock.
- `app/api/v1/recommendations.py`: HTTP 409 for immutable accept/recalculate conflicts; no parallel plan creation.
- `app/config.py`: default-horizon cross-field validation.
- `app/__init__.py`, `pyproject.toml`: version 1.8.14.

Tests:

- Added `tests/unit/test_quant_policy_integrity_2026_06_30.py` with six independent regressions.
- Corrected prior funding test oracles and upgraded policy metric fixtures to v5/cohort evidence.
- Updated native configuration fixture to declare its default horizon.

No migration and no environment variable were added.

## 7. Red → green evidence

Command on pristine 1.8.13 plus the new regression file:

`python -m pytest -q tests/unit/test_quant_policy_integrity_2026_06_30.py`

Result: `6 failed` for the six intended defects. The same command after implementation: `6 passed`.

Full suite changed from `276 passed, 4 skipped` to `282 passed, 4 skipped`.

## 8. Compatibility and rollback

- Database schema unchanged; Alembic head remains `0006_manual_trade_remaining_risk`.
- No `.env` addition. Existing `DEFAULT_HORIZON_HOURS` must already be present in `HORIZONS_HOURS`.
- Candidate/incumbent v4 policy metrics are deliberately incompatible with v5 and must be recomputed.
- Rollback: stop API/worker/trainer, restore 1.8.13 files, and restore/recompute v4 metrics. No database downgrade is required. Do not mix v4/v5 promotion evidence.

## 9. Post-check

Final release checks recorded in `docs/QA_REPORT.md`. Compile, Ruff, full unit suite, Node syntax, Alembic head and clean release integrity pass at 152/152 files. The host `pip check` conflict remains external. PostgreSQL integration, migration round-trip and native doctor were not executed because no safe disposable database/native environment was available.

## 10. Residual risks

- Static research funding remains conservative rather than historically exact; a full solution requires timestamped historical funding intervals/rates aligned to each modeled exit.
- Cohort count reduces pseudo-replication but does not establish regime independence; walk-forward and forward/shadow evidence remain necessary.
- Transaction-lock behavior is unit-tested for call ordering; a two-connection PostgreSQL race test remains unexecuted.
- No claim of profitability is made.

## 11. Recommended next work package

Add a PostgreSQL integration test that races two execution-plan creations for the same `(signal_id, profile_id)` and proves unique monotonic versions plus rollback safety, then add historical point-in-time funding settlement fixtures for backtest attribution. Do not implement live order execution.