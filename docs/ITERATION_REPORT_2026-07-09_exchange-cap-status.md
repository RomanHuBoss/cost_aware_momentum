# Iteration report — 2026-07-09 — exchange-cap-status

## 1. Input archive, SHA-256, source version

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `9c3367670d6c99f644c88d57626fea0bef4a11ef08663cbcc6fbbd1986a7df38`
- Source version: `1.52.12`
- New version: `1.52.13`
- Project root: `cost_aware_momentum-main`
- Python observed in sandbox: `Python 3.13.5`
- Required Python from `pyproject.toml`: `>=3.12`
- Alembic versions present: `0001_initial.py` through `0018_inference_observations.py`
- Expected Alembic head in tests: `0018_inference_observations`
- Baseline production-like files: 122 excluding bytecode/cache files
- Baseline test files: 126 excluding bytecode/cache files
- Baseline documentation files: 1 excluding bytecode/cache files
- Unexpected release artifacts before baseline compile: none found for `.env`, virtualenvs, pycache, pytest cache, `.pyc`, egg-info, build/dist, dumps, or real model artifacts.

## 2. Goal and acceptance criteria

Goal: after this iteration the sizing layer must preserve the difference between exchange instrument caps and exchange minimum-order size failures, and this must be visible in plan status, attrition evidence, and UI labeling.

Acceptance criteria:

1. `exchange_notional_cap=0` produces `BLOCKED_EXCHANGE`, not `BLOCKED_MIN_SIZE`.
2. `limiting_cap` for exchange-cap blocked plans is normalized to `EXCHANGE`.
3. Exchange-cap blocked plans include an operator-readable exchange-limit warning.
4. Exchange-limited but executable plans keep `LIMITED` and include an exchange-limit warning.
5. `BLOCKED_EXCHANGE` attrition maps to `RISK_EXECUTION`.
6. Frontend status label has an explicit `BLOCKED_EXCHANGE` entry.
7. No migration or `.env` change is introduced.
8. No Bybit order create/amend/cancel/withdraw capability is added.

## 3. Read sources and data flow

Read sources:

- `README.md`
- `pyproject.toml`
- `.env.example`
- `app/__init__.py`
- `app/risk/math.py`
- `app/risk/policy.py`
- `app/services/execution.py`
- `app/services/attrition.py`
- `app/bybit/client.py`
- `web/js/app.js`
- `tests/unit/test_risk_math.py`
- `tests/unit/test_candidate_live_attrition_report_2026_07_05.py`
- `tests/unit/test_release_integrity.py`
- `tests/unit/test_release_contract_2026_07_07.py`
- `tests/unit/test_migration_revision_contract.py`
- `scripts/release_integrity.py`

Relevant data flow:

1. Signal geometry is created independently of capital.
2. `calculate_position_plan()` applies capital, risk, margin, liquidity, exchange, and instrument caps.
3. The resulting `PositionPlan.status`, `limiting_cap`, and warnings are persisted into execution-plan diagnostics.
4. Attrition evidence buckets plan terminal stages for model/research diagnostics.
5. UI renders operator-facing status labels.

## 4. Baseline commands and results

| Command | Status | Result |
|---|---:|---|
| `python3 --version` | PASSED | `Python 3.13.5` |
| `python3 -m pip check` | FAILED | `moviepy 2.2.1 has requirement pillow<12.0,>=9.2.0, but you have pillow 12.2.0.` |
| `python3 -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python3 -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python3: No module named ruff` |
| `python3 -m pytest -q` | FAILED | `62 errors in 15.20s`; representative `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python3 scripts/release_integrity.py --write` | PASSED | `Release integrity PASSED: 272 files checked, 272 manifest entries.` |
| `python3 scripts/release_integrity.py` | PASSED | `Release integrity PASSED: 272 files checked, 272 manifest entries.` |
| `python manage.py doctor` | SKIPPED | no safe PostgreSQL configuration |
| `python manage.py test --require-integration` | SKIPPED | no safe PostgreSQL configuration and `psycopg` missing |

Baseline full pytest counts: passed 0 / failed 0 / skipped 0 / xfailed 0 / errors 62 during collection.

## 5. Confirmed defects/gaps

### Defect A — exchange-cap block collapsed into min-order block

- Type: CONFIRMED DEFECT
- Severity: medium
- File: `app/risk/math.py`
- Function: `calculate_position_plan()`
- Path: `exchange_notional_cap` → cap selection → min-size blocked branch → `PositionPlan.status`
- Actual behavior: an exchange notional cap of zero produced `BLOCKED_MIN_SIZE` and limiting cap `MIN_ORDER`.
- Expected behavior: exchange cap breach should be distinct from minimum-order failure: `BLOCKED_EXCHANGE`, limiting cap `EXCHANGE`.
- Impact: operator and attrition diagnostics could misclassify an exchange/instrument cap as a min-order sizing problem. This does not make an unsafe plan executable, but it hides the root cause and can lead to wrong operational remediation.
- Why existing tests missed it: existing min-size, margin, liquidity, and portfolio cap tests did not cover `exchange_notional_cap` or `EXCHANGE_MAX_QTY` blocked mapping.
- Reproduction: add the new regression test with `exchange_notional_cap=Decimal("0")` and run it against 1.52.12.
- Future test: `tests/unit/test_risk_math.py::test_exchange_cap_block_is_not_reported_as_min_order`.

### Defect B — exchange-limited plans lacked an operator warning

- Type: CONFIRMED DEFECT
- Severity: medium
- File: `app/risk/math.py`
- Function: `calculate_position_plan()`
- Path: `exchange_notional_cap` → cap selection → `LIMITED` status warnings
- Actual behavior: an executable but exchange-capped plan returned `LIMITED` with limiting cap `EXCHANGE`, but no warning explaining that exchange limits constrained size.
- Expected behavior: operator warning should state that exchange/instrument limits constrained the size.
- Impact: `LIMITED` status was less actionable for the operator and less consistent with liquidity/margin/portfolio cap behavior.
- Why existing tests missed it: no test asserted warnings for exchange-cap limited plans.
- Future test: `tests/unit/test_risk_math.py::test_exchange_cap_limited_plan_has_operator_warning`.

### Gap C — downstream status consumers did not know `BLOCKED_EXCHANGE`

- Type: CONFIRMED GAP
- Severity: medium
- Files: `app/services/attrition.py`, `web/js/app.js`
- Actual behavior: introducing a distinct exchange-block status would have been classified as `UNKNOWN` by attrition and rendered as a raw fallback string in the UI.
- Expected behavior: attrition should bucket it as `RISK_EXECUTION`, and the UI should show a dedicated Russian label.
- Future test: `tests/unit/test_candidate_live_attrition_report_2026_07_05.py::test_exchange_block_is_risk_execution_attrition`; `node --check web/js/app.js` verifies syntax.

## 6. Plan and actual diff by file

Production:

- `app/risk/math.py`: map `EXCHANGE`/`EXCHANGE_MAX_QTY` blocked min-size branch to `BLOCKED_EXCHANGE`, normalize limiting cap to `EXCHANGE`, add blocked and limited operator warnings.
- `app/services/attrition.py`: classify `BLOCKED_EXCHANGE` as `RISK_EXECUTION`.
- `web/js/app.js`: add UI label for `BLOCKED_EXCHANGE`.
- `app/__init__.py`: bump version to `1.52.13`.

Tests:

- `tests/unit/test_risk_math.py`: add two exchange-cap regression tests.
- `tests/unit/test_candidate_live_attrition_report_2026_07_05.py`: add attrition regression test.

Docs/release:

- `pyproject.toml`, `README.md`, `CHANGELOG.md`, `PATCH_1.52.13.md`
- required docs under `docs/`
- `docs/ITERATION_REPORT_2026-07-09_exchange-cap-status.md`
- `SHA256SUMS` release manifest

Migrations:

- none.

## 7. Red → green evidence

Red command:

```bash
python3 -m pytest -q \
  tests/unit/test_risk_math.py::test_exchange_cap_block_is_not_reported_as_min_order \
  tests/unit/test_risk_math.py::test_exchange_cap_limited_plan_has_operator_warning
```

Red result on unpatched code:

```text
FF [100%]
AssertionError: assert 'BLOCKED_MIN_SIZE' == 'BLOCKED_EXCHANGE'
assert False  # exchange-limit warning absent
2 failed in 0.42s
```

Green command:

```bash
python3 -m pytest -q \
  tests/unit/test_risk_math.py \
  tests/unit/test_candidate_live_attrition_report_2026_07_05.py::test_execution_plan_evidence_is_machine_readable_and_single_terminal \
  tests/unit/test_candidate_live_attrition_report_2026_07_05.py::test_exchange_block_is_risk_execution_attrition
```

Green result:

```text
32 passed in 4.51s
```

## 8. Migrations, API/config/env compatibility

- Alembic migration: not required.
- Alembic head remains `0018_inference_observations`.
- API schema: unchanged.
- Environment variables: unchanged.
- Public Bybit client remains read-only; no order/withdraw endpoints were added.
- Backward compatibility: consumers that do not know `BLOCKED_EXCHANGE` should still treat it as a blocked status via the `BLOCKED_` prefix, while updated UI/attrition now handle it explicitly.

## 9. Post-check commands and results

| Command | Status | Result |
|---|---:|---|
| `python3 -m pip check` | FAILED | same environment conflict: `moviepy 2.2.1` vs `pillow 12.2.0` |
| `python3 -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python3 -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python3: No module named ruff` |
| targeted regression pytest | PASSED | `32 passed in 4.51s` |
| `python3 -m pytest -q` | FAILED | `62 errors in 13.79s`; representative `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | SKIPPED | no safe PostgreSQL configuration |
| `python manage.py test --require-integration` | SKIPPED | no safe PostgreSQL configuration and `psycopg` missing |

## 10. Not verified and why

- Full test suite: blocked at collection by missing `psycopg` in sandbox.
- Ruff static analysis: `ruff` not installed.
- PostgreSQL integration tests: no safe PostgreSQL test database provided.
- `manage.py doctor`: no safe PostgreSQL/local runtime configuration provided.
- End-to-end worker/trainer/model activation/drift/live Bybit flows: out of scope for this one sandbox iteration.

## 11. Residual risks and limitations

- The new status is a public status value. The project UI and attrition were updated, but any external consumer should treat unknown `BLOCKED_*` statuses as blocked.
- Full database-backed behavior still requires validation in an environment with installed project dependencies and a disposable PostgreSQL test database.
- This patch improves diagnostics and fail-closed status semantics; it does not prove strategy profitability.

## 12. Rollback procedure

1. Revert the changes in `app/risk/math.py`, `app/services/attrition.py`, `web/js/app.js`, and the added tests.
2. Restore version markers from `1.52.13` to `1.52.12` in `pyproject.toml`, `app/__init__.py`, and `README.md`.
3. Remove `CHANGELOG.md`, `PATCH_1.52.13.md`, generated docs if the release contract is not desired, and regenerate `SHA256SUMS` for the reverted tree.
4. Re-run targeted risk tests and release-integrity checks.

## 13. Recommended next work package

Prepare a dependency-complete PostgreSQL CI/sandbox profile so `python3 -m pytest -q`, `python3 -m ruff check .`, `python manage.py doctor`, and `python manage.py test --require-integration` can run as release gates without collection failures or unavailable tools.
