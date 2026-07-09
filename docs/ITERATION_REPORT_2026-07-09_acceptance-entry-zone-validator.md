# Iteration Report — 2026-07-09 — acceptance-entry-zone-validator

## 1. Input archive, SHA-256 and source version

- Input archive: `cost_aware_momentum-main.zip`.
- Input SHA-256: `f01af1706cbbbc804760dbf1bb2485b4da314e87af426fa72df194866b37b1d2`.
- Master prompt SHA-256: `2fa2866168069ed14c2d7a57ddffac5bb7b8d2b2df55119efcde0d4fd07937d6`.
- Source version: `1.52.10`.
- Output version: `1.52.11`.
- Alembic head: `0018_inference_observations`.

## 2. Goal and acceptance criteria

Goal: after this iteration, fresh acceptance validation must preserve the immutable decision-time entry-zone contract inside the safety validator itself, so a stale actionable plan cannot be accepted outside the model's price-support zone even when the move is favorable by RR/EV.

Acceptance criteria:

1. `validate_execution_plan_for_acceptance()` rejects executable prices below `signal.entry_low`.
2. `validate_execution_plan_for_acceptance()` rejects executable prices above `signal.entry_high`.
3. The rejection happens before risk/RR/EV checks can accept a favorable but out-of-zone price.
4. The API-level acceptance check remains intact.
5. No migration, `.env` change, order-execution capability, or gate weakening is introduced.
6. Regression test proves red → green on the validator boundary.

## 3. Sources read and affected data flow

Read before/while changing:

- `README.md`.
- `CHANGELOG.md`.
- `PATCH_1.52.10.md`, `PATCH_1.52.9.md`, `PATCH_1.52.8.md`, `PATCH_1.52.7.md`.
- `pyproject.toml`.
- `.env.example`.
- `docs/ARCHITECTURE.md`.
- `docs/QA_REPORT.md`.
- `docs/SPEC_COMPLIANCE.md`.
- `docs/TRACEABILITY.md`.
- `docs/MODEL_CARD.md`.
- `docs/CONFIGURATION.md`.
- `docs/SECURITY.md`.
- `docs/INCIDENT_RUNBOOK.md`.
- `docs/OPERATOR_MANUAL.md`.
- `app/services/execution.py`.
- `app/api/v1/recommendations.py`.
- relevant execution/risk/entry-zone tests.

Affected data flow:

`MarketSignal(entry_low/entry_high)` → `ExecutionPlan` → fresh orderbook FULL-fill VWAP / executable price → `validate_execution_plan_for_acceptance()` → accept/recalculate decision → audit/context snapshot.

## 4. Baseline before changes

Commands were run from the project root before production changes. The shared sandbox lacked two declared tools/dependencies initially, so both raw and normalized observations are recorded.

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | shared sandbox conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE initially; PASSED after installing declared tool | initial: `No module named ruff`; after installing `ruff`, unchanged code passed |
| `python -m pytest -q` | FAILED initially; NOT COMPLETED after declared deps installed | initial: 62 collection errors from missing `psycopg`; after installing `psycopg`, full suite did not complete within 600 s sandbox limit |
| `node --check web/js/app.js` | PASSED | exit 0 |
| focused quant/economics baseline subset | PASSED | `111 passed in 7.40s` |
| `python manage.py release-check` after removing generated caches | PASSED | `Release integrity PASSED: 295 files checked, 295 manifest entries` |
| `python manage.py doctor` | NOT RUN / environment precondition | project-local `.venv` missing; production/user DB was not used |
| `python manage.py test --require-integration` | NOT RUN / environment precondition | safe separate PostgreSQL test DB not configured |

Baseline was not called globally green because full `pytest -q`, integration tests and `pip check` were not clean in this sandbox.

## 5. Confirmed defects/gaps

### CONFIRMED DEFECT — acceptance validator could be called without entry-zone enforcement

- Severity: critical trading-logic safety boundary for direct validator callers; API wrapper already had an independent check.
- File: `app/services/execution.py`, `validate_execution_plan_for_acceptance()`.
- Related API wrapper: `app/api/v1/recommendations.py`, `accept_recommendation()` lines that pre-check `executable_inside_zone`.
- Actual behavior: a direct call to the validator accepted a fresh executable price outside `signal.entry_low` / `signal.entry_high` when risk, funding, liquidity, RR and EV remained acceptable.
- Expected behavior: the validator itself must reject any fresh executable price outside the immutable decision-time entry zone.
- Minimal reproduction: LONG signal with `entry_low=99`, `entry_high=101`, stop `98`, TP `120`, fresh executable `98.9`; the price is outside the signal zone but favorable enough that existing economics checks passed.
- Impact: a stale plan could be accepted outside the model's calibrated price-support contract if a caller reused the validator without the API wrapper pre-check.
- Why existing tests missed it: tests covered plan creation and API acceptance entry-zone checks, but not the direct validator boundary.

## 6. Plan and actual diff

Production files:

- `app/services/execution.py`: validate `entry_low`, `entry_high`, and current executable price in the acceptance validator.

Tests:

- `tests/unit/test_execution_acceptance_safety.py`: add regression test for favorable out-of-zone validator bypass.

Docs/release:

- version markers, changelog, patch note, QA report, compliance, traceability, operator/runbook notes and this report.

No migration/config/API contract change was required.

## 7. Red → green evidence

Red on 1.52.10 after adding the new regression test:

```text
FAILED tests/unit/test_execution_acceptance_safety.py::test_acceptance_validator_rejects_current_entry_outside_signal_zone
E   Failed: DID NOT RAISE <class 'ValueError'>
```

Green after fix:

```bash
python -m pytest -q tests/unit/test_execution_acceptance_safety.py::test_acceptance_validator_rejects_current_entry_outside_signal_zone
# 1 passed in 4.37s
```

Focused suite:

```bash
python -m pytest -q tests/unit/test_execution_acceptance_safety.py tests/unit/test_manual_entry_risk_integrity_2026_07_01.py tests/unit/test_orderbook_vwap_sizing_integrity_2026_07_08.py tests/unit/test_decision_anchor_entry_alignment_2026_07_07.py tests/unit/test_risk_math.py
# 97 passed in 6.00s
```

## 8. Migrations and compatibility

- Alembic migrations: none.
- Alembic head remains `0018_inference_observations`.
- `.env.example`: unchanged.
- API contract: unchanged.
- Model artifact contract: unchanged.
- Advisory-only boundary: unchanged; no Bybit order mutation path was added.
- Rollback risk: low. The patch only adds a fail-closed validation check already mirrored by the API wrapper.

## 9. Post-check

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED / environment limitation | external `moviepy`/`pillow` conflict remains |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | `All checks passed!` |
| `python -m pytest -q tests/unit/test_execution_acceptance_safety.py::test_acceptance_validator_rejects_current_entry_outside_signal_zone` | PASSED | `1 passed in 4.37s` |
| focused execution/risk suite | PASSED | `97 passed in 6.00s` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | NOT RUN | project-local `.venv` not configured in sandbox |
| `python manage.py test --require-integration` | NOT RUN | safe separate PostgreSQL `TEST_DATABASE_URL` not configured |

Release integrity and archive verification are recorded after packaging in the final response.

## 10. What could not be verified

- Full `python -m pytest -q` did not complete within the sandbox limit after declared dependencies were installed.
- PostgreSQL integration suite was not run because no separate safe test database was configured.
- Live Bybit/network smoke was not run and is not claimed.
- The alleged external list of 15 critical + 4 medium + 8 critical defects was not provided, so only independently confirmed defects are claimed.

## 11. Residual risks and limitations

- This patch hardens one confirmed acceptance-boundary defect. It does not claim to exhaustively identify all alleged expert/Fable findings.
- Production readiness still requires clean environment dependency checks, PostgreSQL integration evidence, and forward/paper/shadow evidence.
- Economic profitability is not claimed.

## 12. Rollback procedure

1. Reinstall the previous `1.52.10` release archive.
2. Restart API/worker processes.
3. No migration downgrade is required.
4. If any plan was rejected solely with `Current executable price is outside entry zone`, do not replay it as accepted without fresh signal/plan evidence.

## 13. Recommended next work package

Audit direct service-layer validators against API wrapper pre-checks: identify safety invariants currently enforced only at outer endpoints and add validator-level regression tests for freshness, symbol scope, lifecycle state and immutable plan/signal version binding.
