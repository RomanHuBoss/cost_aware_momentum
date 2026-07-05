# QA Report — 1.25.0

Date: 2026-07-05

## Scope

One bounded P0 safety package: eliminate silent model quality-gate bypass across manual and atomic activation paths while preserving an explicit, audited emergency rollback mechanism.

## Input and baseline

- Input archive: `cost_aware_momentum-1.24.0-candidate-live-attrition(1).zip`
- Input SHA-256: `cc81b57556ab8e4bf296a03b42ce6700bd76aca4f4d492f914553de5371d68ef`
- Source version: `1.24.0`
- Python: `3.13.5` (`requires-python >=3.12`)
- Alembic head: `0014_ui_exposure_ledger`

| Check | Baseline result |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — `592 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |
| `python manage.py doctor` | FAILED as an authoritative release check — clean archive has no project-local `.venv`; equivalent checks were run in an isolated virtual environment |

## Confirmed defect

### Critical — activation safety boundary accepted missing or failed gate evidence

- `scripts/train.py::run` passed `quality_gate=None` when `--activate` was supplied.
- `scripts/model_registry.py::activate_registered_model` validated artifact integrity but never required the persisted gate to have passed.
- `app/ml/lifecycle.py::register_and_activate_model_candidate` did not validate the gate before registry/active-state mutation.

Expected: normal activation must require a complete, internally consistent passed gate. Emergency rollback must be distinguishable, intentional and audited.

Actual: operator CLI paths could silently activate a candidate with missing or failed gate evidence. Existing tests covered background auto-activation and transaction atomicity but not governance invariants across every caller.

## Red → green evidence

Command:

```bash
python -m pytest -q tests/unit/test_model_activation_gate_enforcement_2026_07_05.py
```

Before production changes:

```text
6 failed
Failed: DID NOT RAISE RuntimeError
TypeError: unexpected keyword argument 'emergency_gate_override'
AssertionError: failed candidate must not be activated
```

After production changes:

```text
6 passed
```

The tests independently cover:

- missing gate;
- failed gate;
- contradictory `passed=true` with reasons;
- default rejection of a registered failed model;
- mandatory reason for emergency override;
- audit propagation of override evidence;
- inactive registration when manual `train --activate` fails the gate.

## Post-change verification

| Check | Result |
|---|---|
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| focused activation/recovery/lifecycle tests | PASSED — `43 passed` |
| `python -m pytest -q` | PASSED — `598 passed, 4 skipped, 61 warnings` |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0014_ui_exposure_ledger` |
| `.env.example` parse through `Settings` | PASSED |

## Release assertions

- Version sources report `1.25.0`.
- Activation governance schema is `model-activation-quality-gate-v1`.
- No migration, artifact schema, exchange permission, risk threshold or automatic rollback was introduced.
- Emergency override is one-shot CLI evidence, not a persistent environment switch.
- Bybit client remains read-only; no create/amend/cancel endpoint was added.
- The release includes the non-secret `.env.example` consumed by `manage.py setup`.

## Not run

- `python manage.py test --require-integration`: NOT RUN because no isolated `TEST_DATABASE_URL` was supplied.
- Live PostgreSQL activation/rollback smoke test: NOT RUN.
- Live Bybit calls: NOT RUN; the client was not changed.
- Forward profitability validation: NOT RUN and not claimed.

## Release archive verification

- Staged root: `cost_aware_momentum-1.25.0`.
- 243 files including `SHA256SUMS`; 242 checksum entries.
- Full staged suite repeated successfully: `598 passed, 4 skipped, 61 warnings`.
- Cache/build/credential/model/database artifacts are excluded.
- ZIP is tested with `unzip -t`, fresh extraction and `sha256sum -c SHA256SUMS`.
