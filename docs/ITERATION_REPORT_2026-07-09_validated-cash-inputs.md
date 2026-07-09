# Iteration report — 2026-07-09 — validated-cash-inputs

## 1. Input archive, SHA-256, source version

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `d6675be67511dc9fad590edca0a03bc91443a4ab8efcd9ba42eb65e52de179bb`
- Detected root: `cost_aware_momentum-main/`
- Source version: `1.52.13`
- New version: `1.52.14`
- Python requirement: `>=3.12`
- Local Python used: `Python 3.13.5`
- Alembic version files: `0001_initial.py` ... `0018_inference_observations.py`; no new migration added.
- Baseline file counts before changes: production-like 114, tests 126, docs 14, migrations 20.
- Unexpected release artifacts before baseline: none found for `.env`, virtualenvs, pycache, pytest cache, `.pyc`, egg-info, build/dist, dumps, or real model artifacts. Pycache created by local checks was removed before packaging.

## 2. Goal and acceptance criteria

Goal: after this iteration the shared monetary helper layer must fail closed on invalid cash-flow inputs so negative notionals or negative fee rates cannot silently invert funding sign or create impossible negative fees.

Acceptance criteria:

1. `funding_cash_flow()` rejects negative `position_value`.
2. `funding_cash_flow()` still preserves trader-perspective LONG/SHORT funding sign for valid positive notional.
3. `fee_cash()` rejects negative `fee_rate`.
4. `fee_cash()` validates execution price as positive and finite.
5. Existing risk-math unit suite remains green.
6. No migration or `.env` change is introduced.
7. Advisory-only and Bybit read-only surface are unchanged.

## 3. Read sources and data flow

Read sources:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.13.md`
- `pyproject.toml`
- `.env.example`
- `docs/ARCHITECTURE.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/MODEL_CARD.md`
- `docs/CONFIGURATION.md`
- `docs/SECURITY.md`
- `docs/INCIDENT_RUNBOOK.md`
- `docs/OPERATOR_MANUAL.md`
- `app/risk/math.py`
- `app/services/outcomes.py`
- `tests/unit/test_risk_math.py`

Relevant data flow:

1. Directional funding sign is computed in `funding_return_rate()`.
2. Estimated counterfactual funding uses `funding_cash_flow(direction, entry_notional, funding_rate)`.
3. Execution fee cash may be used by accounting helpers where fee rate and execution price must remain physically valid.
4. Invalid low-level helper inputs must fail closed rather than producing plausible-looking signed cash numbers.

Project map reviewed at high level:

- data ingestion / market data: `app/services/market_data.py`, `app/services/market_snapshots.py`, `app/bybit/client.py`
- features / labels / training / validation: `app/ml/features.py`, `app/ml/labels.py`, `app/ml/training.py`, `app/ml/lifecycle.py`
- artifact lifecycle / runtime: `app/ml/artifact_store.py`, `app/ml/runtime.py`, `app/ml/runtime_selection.py`
- inference / signals / execution plan: `app/services/signals.py`, `app/services/execution.py`
- risk/cost engine: `app/risk/math.py`, `app/risk/policy.py`, `app/risk/liquidity.py`
- account/profile logic: `app/api/v1/capital.py`, `app/api/v1/portfolio.py`
- API schemas/frontend: `app/api/schemas.py`, `app/api/serializers.py`, `web/js/app.js`
- ORM/migrations: `app/db/models.py`, `migrations/versions/`
- audit/idempotency/outbox: `app/services/audit.py`, `app/services/idempotency.py`, model/outbox-related migrations
- tests: `tests/unit/`, `tests/integration_postgres/`

## 4. Baseline commands and exact results

| Command | Status | Result |
|---|---:|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED | `62 errors in 8.76s`; representative `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | SKIPPED | no safe PostgreSQL configuration |
| `python manage.py test --require-integration` | SKIPPED | no safe PostgreSQL configuration and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## 5. Confirmed defects/gaps

### Defect A — negative funding notional inverted funding sign

- Type: CONFIRMED DEFECT
- Severity: medium
- File: `app/risk/math.py`
- Function: `funding_cash_flow()`
- Path: caller-supplied `position_value` -> multiplication by trader-perspective funding return
- Actual behavior: negative `position_value` was accepted and could invert a LONG funding debit into a credit or a SHORT credit into a debit.
- Expected behavior: position value for funding cash-flow must be positive and finite; invalid values must raise `ValueError`.
- Financial impact: invalid signed notional can understate cost or overstate credit in funding accounting if it reaches the helper.
- Why existing tests missed it: tests covered correct funding sign for positive notionals only.
- Reproduction: run the new red test on 1.52.13.
- Future test: `tests/unit/test_risk_math.py::test_funding_cash_flow_rejects_negative_position_value`.

### Defect B — negative fee rate produced impossible negative fees

- Type: CONFIRMED DEFECT
- Severity: medium
- File: `app/risk/math.py`
- Function: `fee_cash()`
- Path: caller-supplied `fee_rate` -> fee cash multiplication
- Actual behavior: negative `fee_rate` returned negative fee cash, creating a hidden rebate.
- Expected behavior: fee cash requires finite quantity, positive finite execution price, and non-negative finite fee rate.
- Financial impact: invalid fee input can overstate realized/net PnL or understate execution cost.
- Why existing tests missed it: tests covered round-trip fee math but not direct helper input validation.
- Reproduction: run the new red test on 1.52.13.
- Future test: `tests/unit/test_risk_math.py::test_fee_cash_rejects_negative_fee_rate`.

## 6. Plan and actual diff by file

Production:

- `app/risk/math.py`
  - `funding_cash_flow()` now validates `position_value` through `positive_finite_decimal`.
  - `fee_cash()` now validates quantity as finite, execution price as positive finite, and fee rate as non-negative finite.

Tests:

- `tests/unit/test_risk_math.py`
  - added `test_funding_cash_flow_rejects_negative_position_value`.
  - added `test_fee_cash_rejects_negative_fee_rate`.

Docs/release:

- `pyproject.toml` bumped to `1.52.14`.
- `app/__init__.py` bumped to `1.52.14`.
- `README.md` release summary updated.
- `CHANGELOG.md` entry added.
- `PATCH_1.52.14.md` added.
- `docs/QA_REPORT.md` updated.
- `docs/SPEC_COMPLIANCE.md` updated.
- `docs/TRACEABILITY.md` updated.
- `docs/ITERATION_REPORT_2026-07-09_validated-cash-inputs.md` added.
- `SHA256SUMS` regenerated after cache cleanup.

No migration files were added or changed.

## 7. Red → green evidence

Red command:

```bash
python -m pytest -q \
  tests/unit/test_risk_math.py::test_funding_cash_flow_rejects_negative_position_value \
  tests/unit/test_risk_math.py::test_fee_cash_rejects_negative_fee_rate
```

Red result on unpatched code after adding tests:

```text
FF [100%]
Failed: DID NOT RAISE <class 'ValueError'>
Failed: DID NOT RAISE <class 'ValueError'>
2 failed in 0.28s
```

Green command:

```bash
python -m pytest -q \
  tests/unit/test_risk_math.py::test_funding_cash_flow_rejects_negative_position_value \
  tests/unit/test_risk_math.py::test_fee_cash_rejects_negative_fee_rate
```

Green result:

```text
.. [100%]
2 passed in 0.11s
```

Full pure risk-math suite:

```bash
python -m pytest -q tests/unit/test_risk_math.py
# ................................ [100%]
# 32 passed in 0.16s
```

## 8. Migrations, API/config/env compatibility

- Migrations: no change; current latest version file remains `0018_inference_observations.py`.
- API compatibility: no public API schema change.
- Config compatibility: no `.env` changes.
- DB compatibility: no schema change.
- Advisory-only compatibility: no order placement, amendment, cancellation, withdrawal, OMS, or EMS functionality added.

## 9. Post-check commands and exact results

| Command | Status | Result |
|---|---:|---|
| `python -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| targeted regression pytest | PASSED | `2 passed in 0.11s` |
| `python -m pytest -q tests/unit/test_risk_math.py` | PASSED | `32 passed in 0.16s` |
| `python -m pytest -q` | FAILED | `62 errors in 6.85s`; representative `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 275 files checked, 275 manifest entries.` |
| `python scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 275 files checked, 275 manifest entries.` |
| `unzip -t final ZIP` | PASSED | archive integrity verified |
| clean re-extract final ZIP | PASSED | one root directory verified |

Post targeted counts: passed 32 / failed 0 / skipped 0 / xfailed 0 / errors 0.

Post full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## 10. What could not be verified and why

- Ruff: not installed in the available Python environment.
- Full pytest: collection imports DB engine code and fails because `psycopg` is not installed.
- PostgreSQL integration tests: no safe PostgreSQL test DB was configured in the sandbox.
- `manage.py doctor`: skipped for the same database-safety reason.
- Bybit connectivity, live/paper/shadow runtime, end-to-end trainer, activation, and drift flows: not run in this sandbox.

## 11. Residual risks and limitations

- This iteration hardens a narrow monetary helper input-validation defect. It does not claim complete validation of PnL, funding, slippage, training, or execution-plan paths.
- Full-suite quality remains unproven in this sandbox until dependencies and a safe PostgreSQL test database are available.
- No live-edge or profitability claims are made.

## 12. Rollback procedure

1. Revert `app/risk/math.py` to version `1.52.13` behavior.
2. Remove the two new tests from `tests/unit/test_risk_math.py`.
3. Revert release/docs files to `1.52.13` and restore the previous `SHA256SUMS`.
4. Run `python -m compileall -q app scripts tests manage.py` and the relevant pytest subset.
5. Repackage only after release integrity passes.

## 13. Recommended next work package

Next recommended package: make test collection dependency diagnostics fail earlier and more explicitly. The current full-suite failure is environmental (`psycopg` missing), but it is noisy and obscures true test failures. A focused package should add an explicit preflight check in the test runner/documentation while preserving PostgreSQL-only behavior and avoiding SQLite fallback.
