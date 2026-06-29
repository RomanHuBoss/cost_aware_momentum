# QA report

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
