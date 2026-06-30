# QA report

## Release 1.8.17 — 2026-06-30

Environment used for reproducible checks:

- Python 3.13.5 in isolated virtual environment `/mnt/data/cam_audit_venv`;
- project installed with `.[dev]`;
- no disposable PostgreSQL integration database or application `.env` was configured.

| Check | Baseline 1.8.16 | Post-change 1.8.17 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 296 passed, 4 skipped, 19 warnings | 304 passed, 4 skipped, 19 warnings |
| explicit unchanged-code regressions | 4 failed | 4 passed |
| new focused/acceptance tests | not present | 8 passed |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic head | `0006_manual_trade_remaining_risk` | `0006_manual_trade_remaining_risk` |
| independent break-even identities | not run | PASSED — 1,000/1,000 |
| release integrity | input archive had no `SHA256SUMS` | PASSED — 154/154 after manifest regeneration |

The explicit red suite proved four unchanged 1.8.16 defects: the API omitted execution-plan economics, exposed the binary break-even shortcut, and returned allocated manual capital for both a read-only profile without an account link and an unknown legacy mode. The same four tests pass after correction. Additional tests cover exact zero-EV mathematics, signal/plan scope separation, snapshot persistence and corruption handling, UI labels/null safety, and the fail-closed profile cases.

The four skipped tests require a separate PostgreSQL database. `python manage.py test --require-integration` and `python manage.py doctor` were NOT RUN because no safe `TEST_DATABASE_URL`, application `.env`, or disposable PostgreSQL instance was available. No migration was added. Technical correctness does not establish strategy profitability.

## Release 1.8.16 — 2026-06-30

Environment used for reproducible checks:

- Python 3.13.5 in an isolated project `.venv`;
- project installed with `.[dev]`;
- no disposable PostgreSQL integration database or application `.env` was configured.

| Check | Baseline 1.8.15 | Post-change 1.8.16 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 288 passed, 4 skipped, 19 warnings | 296 passed, 4 skipped, 19 warnings |
| demonstrated focused regressions | 4 failed, then 1 failed | 5 passed |
| additional acceptance/tick regressions | not present | 3 passed |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic head | `0006_manual_trade_remaining_risk` | `0006_manual_trade_remaining_risk` |
| randomized independent math invariants | not run | PASSED — 1,000 LONG/SHORT cases |
| release integrity | PASSED — 155/155 | PASSED — 157/157 after manifest regeneration |

The red tests proved that unchanged 1.8.15 accepted plans after fresh capital violated the per-trade risk limit, after available margin became insufficient, after current instrument constraints invalidated qty, and after adverse funding increased. A fifth test proved that signal construction did not accept `tick_size` and therefore could publish off-tick levels. All five pass after correction; three additional tests cover the valid acceptance path, legacy off-tick blocking and SHORT rounding.

The four skipped tests require a separate PostgreSQL database. `python manage.py test --require-integration` and `python manage.py doctor` were NOT RUN because no safe `TEST_DATABASE_URL`, application `.env`, or disposable PostgreSQL instance was available. Migration upgrade/downgrade was not required because schema is unchanged. Technical correctness does not establish strategy profitability.

## Release 1.8.15 — 2026-06-30

Environment used for reproducible checks:

- Python 3.13.5 in an isolated virtual environment at `/mnt/data/cam_venv`;
- project installed with `.[dev]`;
- no disposable PostgreSQL integration database or application `.env` was configured.

| Check | Baseline 1.8.14 | Post-change 1.8.15 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 282 passed, 4 skipped, 19 warnings | 288 passed, 4 skipped, 19 warnings |
| focused regressions | 5 failed, then 1 additional failed | 6 passed |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic head | `0006_manual_trade_remaining_risk` | `0006_manual_trade_remaining_risk` |
| release integrity | PASSED — 152/152 | PASSED — 155/155 |

The focused regressions proved six unchanged defects: crossed quotes were accepted in signal and accept paths; an unmodeled TP2 was published; non-finite raw ticker values crashed universe/ticker processing; and UI entry-state used last price instead of the executable side. All six pass after correction.

The four skipped tests require a separate PostgreSQL database. `python manage.py test --require-integration` and `python manage.py doctor` were NOT RUN because no safe `TEST_DATABASE_URL`, application `.env`, or disposable PostgreSQL instance was available. Migration upgrade/downgrade was not required because schema is unchanged. Technical correctness does not establish strategy profitability.


## Release 1.8.14 — 2026-06-30

Environment used for checks:

- Python 3.13.5;
- project dependencies available through an isolated package overlay;
- no isolated PostgreSQL integration database or native project `.venv` was configured.

| Check | Baseline 1.8.13 | Post-change 1.8.14 |
|---|---:|---:|
| `python -m pip check` | FAILED — unrelated host `moviepy`/`pillow` conflict | FAILED — same unrelated host conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 276 passed, 4 skipped | 282 passed, 4 skipped |
| focused regression file | 6 failed | 6 passed |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic heads | `0006_manual_trade_remaining_risk` | `0006_manual_trade_remaining_risk` |
| release integrity | PASSED — 149/149 | PASSED — 152/152 |

The six focused tests failed on the unmodified 1.8.13 code for the intended reasons: favorable funding increased pre-trade SHORT economics; cohort count/weighting was absent; one hourly cohort could satisfy the trade-count gate; accepted plans were recalculated; plan versions were allocated without a transaction lock; and invalid default horizons were accepted. All six pass after correction.

The four skipped tests require a separate PostgreSQL database. `python manage.py test --require-integration` and `python manage.py doctor` were NOT RUN successfully because the archive had no native project `.venv`, no `TEST_DATABASE_URL`, and no safe disposable PostgreSQL configuration. Migration upgrade/downgrade was not required because schema is unchanged. Technical correctness does not establish strategy profitability.

## Release 1.8.13 — 2026-06-30

Environment used for reproducible checks:

- Python 3.13.5 in an isolated project virtual environment;
- project installed with `.[dev]`;
- no isolated PostgreSQL integration database was configured.

| Check | Baseline 1.8.12 | Post-change 1.8.13 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 272 passed, 4 skipped, 19 warnings | 276 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic heads | `0006_manual_trade_remaining_risk` | `0006_manual_trade_remaining_risk` |
| release integrity | PASSED — 147/147 | PASSED — 149/149 |

Four focused regressions failed on the unmodified behavior for the intended reasons: `exit_at_open` was dropped by chronological split, missing split metadata was accepted, direct policy validation silently defaulted the field to `False`, and the affected v3 metric schema remained current. All four pass after correction; the lifecycle gate accepts v4 and rejects v3.

The four skipped tests require an isolated PostgreSQL database and report that `TEST_DATABASE_URL` is not configured. `python manage.py test --require-integration`, migration upgrade/downgrade and `python manage.py doctor` were NOT RUN because no safe PostgreSQL/runtime configuration was available. No migration or `.env` change is required. Candidate/incumbent holdout and research backtest metrics must be recomputed under v4. Technical correctness does not establish strategy profitability.

---

## Release 1.8.12 — 2026-06-30

Environment used for reproducible checks:

- Python 3.13.5 in an isolated project virtual environment;
- project installed with `.[dev]`;
- no isolated PostgreSQL integration database was configured.

| Check | Baseline 1.8.11 | Post-change 1.8.12 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 264 passed, 4 skipped, 19 warnings | 272 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic heads | `0006_manual_trade_remaining_risk` | `0006_manual_trade_remaining_risk` |
| `python manage.py release-check` | PASSED in input release | PASSED — 147 files checked, 147 manifest entries |

Eight focused regressions were executed against the unmodified 1.8.11 implementation and failed for the intended reasons: open-first barrier ordering, adverse gap fill price, full-OHLC validation, exact opening exit time, realized SL promotion loss, and duplicate stop-gap reserve in backtest/PlanOutcome. The same cases pass after correction.

The four skipped tests require an isolated PostgreSQL database and report that `TEST_DATABASE_URL` is not configured. `python manage.py test --require-integration`, migration upgrade/downgrade and `python manage.py doctor` were NOT RUN because no safe PostgreSQL/runtime configuration was available. No migration or `.env` change is required for 1.8.12. Candidate artifacts and policy/backtest metrics must be recomputed before comparison with schema v2 results. Technical correctness does not establish strategy profitability.

---

## Release 1.8.11 — 2026-06-29

Environment used for reproducible checks:

- Python 3.13.5 in an isolated project virtual environment;
- project installed with `.[dev]`;
- no isolated PostgreSQL integration database was configured.

| Check | Baseline 1.8.10 | Post-change 1.8.11 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 252 passed, 4 skipped | 264 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic heads | `0006_manual_trade_remaining_risk` | `0006_manual_trade_remaining_risk` |
| `python manage.py release-check` | PASSED in input release | PASSED — clean manifest, exact count recorded by release-check |

Twelve focused regression cases were executed against the unmodified 1.8.10 implementation and failed for the intended reasons: horizon-sleeve accounting, exact barrier/horizon metadata, strict leverage, hourly/OHLC validation, future manual fills, plan-time funding projection and policy-metric schema. The same cases pass after correction.

The four skipped tests require an isolated PostgreSQL database and report that `TEST_DATABASE_URL` is not configured. `python manage.py test --require-integration`, migration upgrade/downgrade and `python manage.py doctor` were NOT RUN because no safe PostgreSQL/runtime configuration was available. No migration or `.env` change is required for 1.8.11. Technical correctness does not establish strategy profitability.

---

## Release 1.8.10 — 2026-06-29

Environment used for reproducible checks:

- Python 3.13.5 in an isolated virtual environment outside the release tree;
- project installed with `.[dev]`;
- PostgreSQL integration database was not configured.

| Check | Baseline 1.8.9 | Post-change 1.8.10 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 198 passed, 4 skipped | 252 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic heads | `0005_plan_outcome_invalid_input` | `0006_manual_trade_remaining_risk` |
| `python manage.py release-check` | FAILED: manifest referenced four absent files | PASSED — 157/157 after manifest regeneration |

Independent regression evidence was collected in two stages on the unmodified implementation: the initial quantitative/econometric audit produced `33 failed`, and the follow-up boundary/risk/artifact audit produced `20 failed, 32 passed`. After correction, the corresponding audit module reports `53 passed`; the complete suite reports `252 passed, 4 skipped`.

The four skipped tests require an isolated PostgreSQL database and report that `TEST_DATABASE_URL` is not configured. `python manage.py test --require-integration` and migration upgrade/downgrade were therefore NOT RUN. `python manage.py doctor` was NOT RUN because no runtime `.env` or safe PostgreSQL database was configured. Apply Alembic revision `0006_manual_trade_remaining_risk` before starting 1.8.10. No new environment variable is required. Technical correctness does not establish profitability.

---

## Release 1.8.9 — 2026-06-29

Environment used for reproducible checks:

- Python 3.13.5 in an isolated virtual environment outside the release tree;
- project installed with `.[dev]`;
- PostgreSQL integration database was not configured.

| Check | Baseline 1.8.8 | Post-change 1.8.9 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 194 passed, 4 skipped | 198 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic heads | `0005_plan_outcome_invalid_input` | `0005_plan_outcome_invalid_input` |

New regression module `tests/unit/test_directional_pair_integrity.py` independently reproduces four manifestations of one research/live parity defect. Red evidence on unmodified 1.8.8: `4 failed`. Green evidence after correction: `4 passed`.

The four skipped tests require an isolated PostgreSQL database and report that `TEST_DATABASE_URL` is not configured. `python manage.py doctor` and `python manage.py test --require-integration` were attempted and classified as UNAVAILABLE: both stopped before their checks with `Виртуальная среда не найдена`, because the clean release tree intentionally has no local `.venv`; no safe PostgreSQL test database was configured. No migration, API or `.env` change is required. Model retraining and recalculation of research metrics are recommended because incomplete directional cohorts are now removed atomically. Technical correctness does not establish profitability.

---

## Release 1.8.8 — 2026-06-29

Environment used for reproducible checks:

- Python 3.13.5 in an isolated virtual environment outside the release tree;
- project installed with `.[dev]`;
- PostgreSQL integration database was not configured.

| Check | Baseline 1.8.7 | Post-change 1.8.8 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 184 passed, 4 skipped | 194 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic heads | `0005_plan_outcome_invalid_input` | `0005_plan_outcome_invalid_input` |

New regression module `tests/unit/test_quant_correctness_hardening.py` reproduces all ten defects independently. Red evidence on unmodified 1.8.7: `10 failed`. Green evidence after correction: `10 passed`.

The four skipped tests require an isolated PostgreSQL database and report that `TEST_DATABASE_URL` is not configured. `python manage.py doctor` and `python manage.py test --require-integration` were not run because no safe PostgreSQL test configuration was available. No migration or `.env` change is required. Model retraining is recommended because feature-state segmentation and holdout policy event accounting changed. Technical correctness does not establish profitability.

---

## Release 1.8.7 — 2026-06-29

Environment used for reproducible checks:

- Python 3.13.5 in an isolated virtual environment outside the release tree;
- project installed with `.[dev]`;
- PostgreSQL integration database was not configured.

| Check | Baseline 1.8.6 | Post-change 1.8.7 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q -rs` | 172 passed, 4 skipped | 184 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic heads | `0005_plan_outcome_invalid_input` | `0005_plan_outcome_invalid_input` |
| Release integrity | FAILED: missing `PATCH_1.8.6.md` | PASSED after clean manifest regeneration |

The four skipped tests require an isolated PostgreSQL database and explicitly report `TEST_DATABASE_URL is not configured`. `python manage.py doctor` and `python manage.py test --require-integration` were not run because no safe local PostgreSQL test configuration was available.

New regression coverage:

- LONG acceptance uses ask and SHORT uses bid; invalid executable side fails closed;
- stale read-only account snapshot returns zero unverified capital and blocks the execution plan;
- acceptance acquires the global transaction advisory lock before reading open risk/capital;
- a stop beyond the estimated liquidation boundary blocks at leverage 3 as well as at higher leverage;
- unsafe account snapshot age configuration is rejected.

Red evidence: the new test module failed during collection because `assess_liquidation_proximity` did not exist. Green evidence: `12 passed` separately. No database migration is required. `.env.example` adds `MAX_ACCOUNT_SNAPSHOT_AGE_SECONDS=180`; the default is backward compatible. Technical correctness does not establish profitability.

---

## Release 1.8.5 — 2026-06-29

Environment used for reproducible checks:

- Python 3.13.5;
- project installed with `.[dev]`;
- PostgreSQL integration database was not configured.

| Check | Result |
|---|---:|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q -rs` | 169 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | `0005_plan_outcome_invalid_input` |

The four skipped tests require an isolated PostgreSQL database and explicitly report `TEST_DATABASE_URL is not configured`.

New or expanded regression coverage:

- overlapping full-horizon returns use non-overlapping capital sleeves;
- simultaneous symbols are equal-weighted inside a cohort;
- first-period drawdown remains visible;
- direction selection uses net `EV/R`, not raw expected rate;
- exit fee uses actual exit notional;
- live signal geometry accepts artifact stop/TP multipliers;
- runtime loads and exposes artifact multipliers;
- projected funding excludes a settlement exactly at the planning start boundary.

No database migration or `.env` change is required. Existing artifacts remain compatible through default barrier multipliers. Backtest results produced before 1.8.5 are not directly comparable because the portfolio accounting semantics changed.

---

## Release 1.8.4 — 2026-06-29

Environment used for reproducible checks:

- Python 3.13.5 in an isolated virtual environment outside the release tree;
- project installed with `.[dev]`;
- PostgreSQL integration database was not configured.

| Check | Baseline 1.8.3 | Post-change 1.8.4 |
|---|---:|---:|
| `python -m pip check` | PASSED | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED | PASSED |
| `python -m ruff check .` | PASSED | PASSED |
| `python -m pytest -q` | 160 passed, 4 skipped | 162 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED | PASSED |
| Alembic heads | `0005_plan_outcome_invalid_input` | `0005_plan_outcome_invalid_input` |

The four skipped tests are PostgreSQL integration tests and explicitly report `TEST_DATABASE_URL is not configured`.

New regression tests:

- `test_runtime_exposes_both_directional_scenarios`;
- `test_signal_direction_is_selected_by_exact_net_ev_not_fixed_runtime_utility`.

Red evidence before implementation: the new test module failed during collection because `select_cost_aware_scenario` did not exist. Green evidence after implementation: `2 passed` separately and `162 passed, 4 skipped` in the full suite.

No database migration or `.env` change is required. Technical correctness does not establish strategy profitability.
