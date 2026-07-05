# QA Report — 1.15.0

Date: 2026-07-05

Scope: immutable prospective execution-plan opportunity ledger, pre-decision feature integrity, chronological out-of-sample operator propensity diagnostics, all-eligible outcome benchmark and stabilized inverse-probability-of-selection weighting.

## Environment

- Python: 3.13.5
- Project requirement: Python >=3.12
- Input release: 1.14.0
- Output release: 1.15.0
- Input ZIP SHA-256: `77c293d747f45a7c4897ef1c88f8c95b079404c49049bc035002fe422e4be96e`
- Input Alembic head: `0010_orderbook_exec_evidence`
- Output Alembic head: `0011_selection_experiment`
- Baseline tree: 73 app/script Python files, 64 test Python files, 15 documentation files, 10 migrations

## Baseline before code changes

| Check | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5. |
| `python -m pip check` | FAILED | Host-level unrelated conflict: `moviepy 2.2.1` requires `pillow<12`, host has `pillow 12.2.0`. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 514 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m alembic heads` | PASSED | Single head `0010_orderbook_exec_evidence`. |

## Red → green

The new regression module was copied into an untouched 1.14.0 tree and executed:

```text
python -m pytest -q tests/unit/test_operator_selection_bias_2026_07_05.py
```

Red result: collection failed with `ModuleNotFoundError: No module named 'app.research'`.

Green result on 1.15.0:

```text
7 passed
```

A further execution-plan transaction regression confirms that `create_execution_plan()` invokes the ledger builder with the plan, signal, release version and timezone-aware planning timestamp.

## Post-change checks

| Check | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED | Same external host `moviepy`/`pillow` conflict; project dependencies were not changed. |
| `python -m compileall -q app scripts tests manage.py` | PASSED | Exit 0. |
| `python -m ruff check .` | PASSED | Exit 0. |
| `python -m pytest -q` | PASSED | 522 passed, 4 skipped. |
| `node --check web/js/app.js` | PASSED | Exit 0. |
| `python -m alembic heads` | PASSED | Single head `0011_selection_experiment`. |
| `python -m pytest -q -rs tests/integration_postgres` | SKIPPED | 4 skipped because `TEST_DATABASE_URL` is not configured. |
| `python manage.py doctor` | FAILED (environment) | Project `.venv` was not provisioned. |
| `python manage.py test --require-integration` | NOT RUN | Command requires project `.venv`; no isolated PostgreSQL test database was used. |

## Mathematical and temporal checks

- Feature set is exact and rejects added outcome-derived keys.
- Canonical hash changes when a stored feature changes.
- ACCEPT, REJECT and NO_DECISION are retained in one cohort.
- Propensity predictions for an evaluated block use only earlier plan opportunities.
- Synthetic selection bias is reduced by IPSW relative to the observed all-eligible benchmark.
- Class collapse does not emit a corrected estimate.
- Ledger corruption blocks the complete report.
- The report explicitly sets `causal_effect_claimed=false`.

## Interpretation

The direct all-eligible counterfactual mean is the primary estimate because plan outcomes are resolved for selected and unselected eligible plans. IPSW is a diagnostic of how the accepted subset differs in observed pre-decision covariates. It does not establish a causal effect of operator action, actual exchange profitability or absence of unobserved selection factors.

## Release archive verification

| Check | Result |
|---|---|
| Clean staged manifest | PASSED, 193/193 files |
| Clean staged full suite | 522 passed, 4 skipped |
| Clean staged compile/Ruff/Node checks | PASSED |
| Clean staged Alembic head | `0011_selection_experiment (head)` |
| ZIP structural test | PASSED (`unzip -t`) |
| Fresh re-extraction manifest | PASSED, 193/193 files |
| Fresh re-extraction full suite | 522 passed, 4 skipped |
| Fresh re-extraction compile/Ruff/Node checks | PASSED |
| Fresh re-extraction Alembic head | `0011_selection_experiment (head)` |

Generated caches were removed after testing and the manifest was regenerated before final packaging.
