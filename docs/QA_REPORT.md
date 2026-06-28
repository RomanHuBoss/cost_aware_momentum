# QA report

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
