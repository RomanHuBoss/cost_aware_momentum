# Iteration Report — fail-closed model activation

Date: 2026-07-05  
Target release: 1.25.0

## 1. Input archive and source state

- Archive: `cost_aware_momentum-1.24.0-candidate-live-attrition(1).zip`
- SHA-256: `cc81b57556ab8e4bf296a03b42ce6700bd76aca4f4d492f914553de5371d68ef`
- Source version: `1.24.0`
- Python requirement: `>=3.12`
- Baseline runtime: Python `3.13.5`
- Alembic head: `0014_ui_exposure_ledger`
- Source counts before changes: 95 production files, 76 test files, 25 documentation files.
- The input archive had no secrets/model/database dumps, but omitted `.env.example`; editable dependency installation generated local caches/egg-info only in the working copy, which are excluded from release staging.

## 2. Goal and acceptance criteria

> After this iteration, no normal model-activation path may interpret missing, failed or contradictory quality-gate evidence as approval; emergency rollback without passed evidence must require an explicit audited reason.

Acceptance criteria:

1. Atomic candidate activation rejects `None`, failed and internally contradictory gates before artifact or database mutation.
2. Manual `train --activate` evaluates the standard gate and leaves failed candidates inactive.
3. Registered-model activation defaults to fail-closed on missing/failed gate evidence.
4. Emergency rollback remains possible only through an explicit override flag plus non-empty reason.
5. Override and original gate evidence are included in the activation audit payload.
6. Existing checksum, horizon, compare-and-swap and transaction invariants remain green.
7. No migration, new environment setting, artifact schema or risk-threshold change.

## 3. Sources and affected data flow

Read:

- `README.md`, `CHANGELOG.md`, patches 1.22.0–1.24.0;
- `docs/SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `QA_REPORT.md`;
- architecture, security, configuration, operator and incident documents;
- `app/ml/lifecycle.py`, `app/workers/trainer.py`;
- `scripts/train.py`, `scripts/model_registry.py`;
- model lifecycle, atomic promotion, recovery and trainer tests.

Affected flow:

training metrics → `evaluate_quality_gate` → candidate registry metrics → activation governance → artifact validation → PostgreSQL active-version compare-and-swap → audit/outbox → runtime refresh.

## 4. Baseline

Executed before code changes in a new isolated virtual environment:

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `592 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |
| `python manage.py doctor` | FAILED — release root intentionally lacked `.venv`; equivalent checks were executed directly in the isolated environment |

## 5. Confirmed defect

### CRITICAL — silent quality-gate bypass during model activation

Evidence:

- `scripts/train.py::run` supplied `quality_gate=None` to atomic activation whenever `--activate` was requested.
- `scripts/model_registry.py::activate_registered_model` inspected only artifact integrity/horizon and active registry state.
- `app/ml/lifecycle.py::register_and_activate_model_candidate` accepted any gate value and immediately proceeded toward active-state mutation.

Minimal reproduction was encoded in the new test module. On 1.24.0:

- missing, failed and contradictory gates did not raise;
- a registered failed candidate activated normally;
- no explicit emergency override API existed;
- manual train attempted activation with `quality_gate=None`.

Impact: model-quality, temporal-validation, policy-economics and incumbent-relative protections could be bypassed by a routine-looking operator command, allowing a technically valid but rejected artifact to become active. This can lead to financially harmful advisory recommendations. The path required operator invocation, but the absence of any explicit override marker made the bypass silent and non-reviewable.

Why existing tests missed it: tests validated background trainer gating, atomic transaction behavior and artifact recovery, but did not assert that every state-changing activation caller supplied and enforced the same gate contract.

## 6. Plan and actual diff

Production:

- `app/ml/lifecycle.py`
  - added `MODEL_ACTIVATION_QUALITY_GATE_SCHEMA`;
  - added `require_passed_quality_gate`;
  - enforced gate before artifact/DB work in atomic activation;
  - included activation-governance evidence in audit payload.
- `scripts/train.py`
  - evaluates gate for every manual candidate;
  - registers failed activation requests inactive;
  - publishes gate and explanatory result.
- `scripts/model_registry.py`
  - validates persisted gate by default;
  - added explicit emergency override + mandatory reason;
  - audits original gate and override evidence.
- `app/__init__.py`, `pyproject.toml`
  - version 1.25.0.

Tests:

- new `tests/unit/test_model_activation_gate_enforcement_2026_07_05.py` with six regressions.

Release/documentation:

- restored `.env.example` required by `manage.py setup`;
- added `PATCH_1.25.0.md`;
- updated README, changelog, architecture, security, configuration, operator, incident, QA, compliance and traceability documents.

## 7. Red → green evidence

Red command:

```bash
python -m pytest -q tests/unit/test_model_activation_gate_enforcement_2026_07_05.py
```

Red result:

```text
6 failed
Failed: DID NOT RAISE RuntimeError
TypeError: activate_registered_model() got an unexpected keyword argument 'emergency_gate_override'
AssertionError: failed candidate must not be activated
```

Green result:

```text
6 passed
```

Focused lifecycle/regression group:

```text
43 passed
```

## 8. Migration, API, configuration and compatibility

- Migration: none; head remains `0014_ui_exposure_ledger`.
- API/UI contract: unchanged.
- `.env` names: unchanged.
- Artifact/runtime feature schema: unchanged; retraining not required.
- Normal activation of legacy registered versions without a passed gate now fails closed.
- Emergency rollback remains available with explicit flag and incident reason.
- The override does not bypass artifact checksum, version, horizon or concurrent-active-version validation.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `598 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |
| load `Settings` from `.env.example` | PASSED |

## 10. Not verified

- PostgreSQL integration suite: no isolated `TEST_DATABASE_URL`.
- Live activation/rollback smoke test against the user's database.
- Live Bybit behavior, because the read-only client was not modified.
- Economic profitability or recommendation frequency improvement.

## 11. Residual risks and limitations

- A privileged operator can still intentionally invoke emergency override. This is required for disaster rollback and is now explicit/audited, not prohibited.
- Database-owner compromise can modify registry/audit data outside application controls.
- Experiment preregistration/PBO/DSR evidence is still not automatically bound to model promotion; the specification continues to mark that separate gap as open.
- Existing active models are not automatically deactivated by this patch.

## 12. Rollback procedure

1. Stop API, worker and trainer.
2. Restore the previous 1.24.0 source tree.
3. No database downgrade is needed.
4. Restart processes; the existing active registry row remains unchanged by source rollback.
5. Preserve 1.25.0 activation audit events for incident review; do not delete them.

## 13. Recommended next work package

Bind automatic candidate promotion to a prospective immutable experiment-family governance decision without turning PBO/DSR into a post-hoc tuning knob. The design must distinguish routine retraining from explicit research families and must not block emergency rollback or claim profitability.

## 14. Release archive verification

- Root directory: `cost_aware_momentum-1.25.0`.
- Expected release file count: 243 including `SHA256SUMS`.
- Expected checksum entries: 242.
- The staged tree passed the full suite before packaging.
- The final ZIP is verified by `unzip -t`, fresh extraction, `sha256sum -c SHA256SUMS`, release-boundary scan and a second full test run from the extracted root.
