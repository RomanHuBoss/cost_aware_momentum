# Iteration Report — 2026-07-08 — signal-economics-diagnostics

## 1. Input archive, SHA-256 and source version

- Input archive: `cost_aware_momentum-1.52.9-trainer-progress-clarity.zip`.
- Input SHA-256: `36bcdbedaf8e6b5171e09850dd15002b4ed6b5dba01fdfae805793a54aeaa2f7`.
- Source version: `1.52.9`.
- Output version: `1.52.10`.

## 2. Goal and acceptance criteria

Goal: after this iteration, fail-closed market-signal economics skips must expose an exact safe reason and enough point-in-time context for operators to distinguish a normal quote-outside-entry-zone block from tick/spec/alignment defects, without publishing an unsafe signal.

Acceptance criteria:

1. `ValueError("Executable quote moved outside the decision-time entry zone")` is classified as `quote_outside_decision_entry_zone`.
2. JSON logs include `reason_code`, `contract_error`, `reason_detail`, bid/ask, decision anchor, entry band and tick size.
3. Inference `symbol_outcomes` include the same per-symbol detail for economics skips.
4. Existing fail-closed behavior is preserved: the symbol is skipped and no signal is published.
5. No migration, `.env` change or order-execution capability is introduced.
6. New regression tests prove red → green.

## 3. Sources read and affected data flow

Read before/while changing:

- `README.md`.
- `CHANGELOG.md`.
- `PATCH_1.52.9.md`, `PATCH_1.52.8.md`, `PATCH_1.52.7.md`.
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
- `app/services/signals.py`.
- `app/logging.py`.
- relevant unit tests around inference attrition and incident diagnostics.

Affected data flow:

`confirmed candle + ticker + instrument spec + model predictions` → `select_cost_aware_scenario()` → `ValueError` on invalid signal economics → `classify_signal_economics_skip()` → `record_symbol_outcome()` / JSON logger → worker/job diagnostics and operator log review.

## 4. Baseline before changes

Commands were run from the project root before production changes.

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | shared sandbox conflict: `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | `/opt/pyvenv/bin/python: No module named ruff` |
| `python -m pytest -q` | FAILED / environment limitation | 62 collection errors from missing declared dependency `psycopg` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | FAILED / environment precondition | project-local `.venv` missing: `Виртуальная среда не найдена. Сначала выполните: python manage.py setup` |
| `python manage.py test --require-integration` | FAILED / environment precondition | project-local `.venv` missing before integration dispatch; safe PostgreSQL test DB not configured |

Baseline was not green due to sandbox dependency gaps.

## 5. Confirmed defects/gaps

### CONFIRMED DEFECT — opaque signal-economics skip diagnostics

- Severity: medium operational diagnostics / incident triage.
- File: `app/services/signals.py`, `publish_hourly_signals()` catch around `select_cost_aware_scenario()`.
- File: `app/logging.py`, `JsonFormatter` whitelist.
- Actual behavior: every scenario-selection `ValueError` became `reason_code=invalid_signal_economics`, and the `error` extra field was not included in JSON logs.
- Expected behavior: fail-closed skip remains, but the reason and safe market context are visible.
- Impact: a full-symbol batch of warnings could not be distinguished as quote drift outside decision-time entry band versus tick/spec bug.
- Why tests missed it: previous formatter tests covered decision-time contract warnings, not the signal-economics skip path.

## 6. Plan and actual diff

Production files:

- `app/logging.py`: extend the safe JSON-field whitelist for signal-economics diagnostics.
- `app/services/signals.py`: classify economics rejects and attach per-symbol diagnostics.

Tests:

- `tests/unit/test_signal_economics_diagnostics_2026_07_08.py`.

Docs/release:

- version markers, changelog, patch note, QA report, compliance, traceability, operator/runbook notes and this report.

No migration/config/API contract change was required.

## 7. Red → green evidence

Red on 1.52.9 after adding the new regression tests:

```text
FAILED test_json_formatter_preserves_signal_economics_skip_context
KeyError: 'reason_detail'

FAILED test_invalid_signal_economics_skip_is_classified_in_diagnostics
AssertionError: {'invalid_signal_economics': 1} == {'quote_outside_decision_entry_zone': 1}
```

Green after fix:

```bash
python -m pytest -q tests/unit/test_signal_economics_diagnostics_2026_07_08.py
# 2 passed in 0.52s

python -m pytest -q tests/unit/test_signal_economics_diagnostics_2026_07_08.py tests/unit/test_attrition_inference_instrumentation_2026_07_05.py
# 3 passed in 0.55s
```

## 8. Migrations and compatibility

- Alembic migrations: none.
- Alembic head remains `0018_inference_observations`.
- `.env`: no new variables.
- API schema: no breaking change.
- Advisory-only: unchanged.
- PostgreSQL-only: unchanged.
- Fail-closed behavior: preserved.

## 9. Post-check

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED / environment limitation | same external `moviepy`/`pillow` conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | `ruff` not installed |
| `python -m pytest -q` | FAILED / environment limitation | collection still fails before suite execution from missing `psycopg` |
| `python -m pytest -q tests/unit/test_signal_economics_diagnostics_2026_07_08.py` | PASSED | 2 passed |
| `python -m pytest -q tests/unit/test_signal_economics_diagnostics_2026_07_08.py tests/unit/test_attrition_inference_instrumentation_2026_07_05.py` | PASSED | 3 passed |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py doctor` | FAILED / environment precondition | missing project-local `.venv` |
| `python manage.py test --require-integration` | FAILED / environment precondition | missing project-local `.venv`; no safe TEST_DATABASE_URL configured |
| `python -B -m scripts.release_integrity --write` | PASSED | manifest written and verified |

## 10. Not verified

- Full test suite due to missing `psycopg` in the sandbox.
- Ruff due to missing `ruff` module.
- PostgreSQL integration tests due to missing safe test database and project-local `.venv`.
- Live Bybit/network smoke due to no network credentials and no live smoke request in scope.
- Economic edge/profitability: not claimed.

## 11. Residual risks and limitations

- `reason_code` classification is based on stable validation messages emitted by `select_cost_aware_scenario()`. If future validation text changes, the fallback remains fail-closed but may revert to `invalid_signal_economics` until a new mapping is added.
- The new diagnostics expose market prices and tick/entry-band context; they do not expose secrets or credentials.
- A large batch of `quote_outside_decision_entry_zone` should still be investigated as a pipeline-lag/entry-zone problem; the patch only makes the reason visible.

## 12. Rollback procedure

Revert to 1.52.9 package if the new diagnostics cause unexpected operator-log compatibility issues. No schema rollback is needed. Restart API/inference worker after rollback.

## 13. Recommended next work package

Add an operator-facing hourly inference summary panel/API field that aggregates skip counts and top reason examples from the latest worker job, without changing policy gates or execution behavior.
