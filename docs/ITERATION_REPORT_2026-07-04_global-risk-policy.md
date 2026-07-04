# Iteration Report — global capital risk policy

## 1. Input archive, hash and versions

- Input: `cost_aware_momentum-main.zip`.
- SHA-256: `bb815e0adc6f78853a3aad15441eb88ae3900cc073c275a620013de601045ce8`.
- Source version: `1.9.2`.
- Result version: `1.9.3`.
- Python requirement: `>=3.12`; test runtime: Python 3.13.5.
- Alembic: 9 revisions, one head `0009_candle_receipt_availability`; no migration in this patch.

## 2. Iteration goal and acceptance criteria

After this iteration, a capital profile must not weaken process-wide risk/leverage ceilings, which is confirmed by policy, API, plan-construction, acceptance, portfolio and frontend regressions.

Acceptance criteria:

1. `risk_rate <= max_total_risk_rate <= MAX_TOTAL_OPEN_RISK_RATE` is mandatory.
2. `default_leverage <= max_leverage <= MAX_LEVERAGE` is mandatory.
3. Omitted create-profile values come from current runtime settings.
4. Create/patch/activate reject unsafe values before persistence or recalculation.
5. Unsafe persisted legacy profiles cannot produce or retain an actionable accepted plan.
6. Portfolio diagnostics do not report the unsafe profile ceiling as the effective limit.
7. Existing valid behavior remains green; no migration/new dependency/order mutation is introduced.

## 3. Sources read and affected data flow

Read before modification:

- `README.md`, `CHANGELOG.md`, `PATCH_1.9.2.md`;
- `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- recent iteration reports;
- source DOCX specification relevant to risk, advisory-only and fail-closed behavior;
- risk math, execution, capital/recommendation/portfolio APIs, serializers, frontend, ORM and unit tests.

Affected flow:

`profile API/UI or persisted legacy row → centralized global policy validation → account-dependent sizing → immutable plan snapshot → fresh acceptance revalidation → portfolio diagnostics/UI`.

Market signal direction, entry geometry, TP/SL, probabilities, ML artifact and training gates are not changed by profile capital.

## 4. Baseline

The system Python lacked project dependencies; this was classified as an environment failure. A clean `.venv` was created with the native setup workflow and the baseline repeated before production edits.

| Command | Result |
|---|---|
| `.venv/bin/python --version` | PASSED — Python 3.13.5 |
| `.venv/bin/python -m pip check` | PASSED |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED |
| `.venv/bin/python -m ruff check .` | PASSED |
| `.venv/bin/python -m pytest -q` | PASSED — **435 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED |
| `.venv/bin/python -m alembic heads` | PASSED — one head |
| input release integrity | PASSED — 173/173 |
| `manage.py doctor` | FAILED due local environment: default secrets, missing PostgreSQL CLI/server |
| `manage.py test --require-integration` | NOT RUN — no isolated PostgreSQL URL |

## 5. Confirmed defect and evidence

### CRITICAL — runtime ceiling was declarative, profile ceiling was effective

Files and paths:

- `app/config.py::Settings`: default global total risk 0.02 and max leverage 5;
- `app/api/schemas.py::CapitalProfileCreate/Patch`: total profile risk allowed up to 0.20;
- `app/api/v1/capital.py`: payload persisted without `Settings` comparison;
- `app/services/execution.py::create_execution_plan`: `c_eff * profile.max_total_risk_rate`;
- `app/services/execution.py::validate_execution_plan_for_acceptance` and `app/api/v1/recommendations.py`: acceptance used persisted profile ceiling.

Minimal reproduction under default settings:

- profile total-risk rate: 0.20;
- expected: blocked because global ceiling is 0.02;
- actual before fix: plan `ACTIONABLE`, acceptance HTTP 200 / `ACCEPTED`.

Financial impact: up to 20% open stress-risk budget could be authorized where the runtime claimed a 2% ceiling. Leverage configuration had the same architectural bypass when configured below profile schema limits.

Why tests missed it: configuration validation and profile/plan tests did not assert the cross-layer dominance of process-wide settings.

No evidence was available to attribute the user's specific losses or rare recommendations to this defect. That requires database/job/model/fill data.

## 6. Plan and actual diff

Production:

- `app/risk/policy.py` — centralized finite/cross-field/global ceiling contract.
- `app/api/schemas.py` — structural validation; runtime policy owns dynamic ceilings/defaults.
- `app/api/v1/capital.py` — runtime defaults plus create/patch/activate fail-closed validation.
- `app/services/execution.py` — legacy profile validation in planning and acceptance; safe non-actionable diagnostic fallback.
- `app/api/v1/recommendations.py` — total-risk acceptance uses validated policy value.
- `app/api/v1/portfolio.py` — effective global cap and invalid-policy diagnostics.
- `web/js/app.js` — no hard-coded total/margin defaults; total profile limit displayed.

Tests:

- new `tests/unit/test_capital_profile_policy_2026_07_04.py`;
- strengthened `test_execution_acceptance_safety.py`;
- fixture contract updates in account-scope/manual-entry tests.

Release/docs:

- version sources, README, architecture, configuration, operator/security/incident docs;
- changelog, `PATCH_1.9.3.md`, QA, compliance, traceability, this report and manifest.

## 7. Red → green evidence

Command:

```bash
python -m pytest -q \
  tests/unit/test_execution_acceptance_safety.py::test_execution_plan_blocks_profile_above_global_total_risk_cap \
  tests/unit/test_execution_acceptance_safety.py::test_acceptance_rejects_profile_above_global_total_risk_cap
```

RED on source behavior:

```text
expected BLOCKED_INVALID_INPUT, actual ACTIONABLE
expected HTTP 409, actual HTTP 200
2 failed
```

GREEN after fix:

```text
2 passed in 1.27s
```

New independent contracts also verify runtime defaults, risk hierarchy, leverage ceiling, patch-before-mutation and absence of frontend hard-coded overrides.

## 8. Migration, API/config/env compatibility

- Migration: none; no ORM/schema change.
- Alembic head unchanged: `0009_candle_receipt_availability`.
- New dependencies: none.
- New `.env` variables: none.
- Existing valid profile payloads remain accepted.
- Create-profile policy fields may be omitted; runtime settings become authoritative defaults.
- Explicit unsafe values are now rejected with HTTP 422. This is an intentional safety tightening, not a data-schema breaking change.
- Existing unsafe legacy rows remain in DB for auditability but cannot be activated, planned or accepted until corrected.

## 9. Post-check

| Command | Result |
|---|---|
| `.venv/bin/python -m pip check` | PASSED |
| `.venv/bin/python -m compileall -q app scripts tests manage.py` | PASSED |
| `.venv/bin/python -m ruff check .` | PASSED |
| `.venv/bin/python -m pytest -q` | PASSED — **444 passed, 4 skipped, 55 warnings** |
| `node --check web/js/app.js` | PASSED |
| `.venv/bin/python -m alembic heads` | PASSED — one head |
| `manage.py doctor` | FAILED / environment only |
| PostgreSQL integration suite | NOT RUN — isolated server/URL unavailable |
| final manifest, archive test and clean re-extraction | PASSED — 177/177; `unzip -t` passed; re-extracted tree passed release-check |

No previously green test regressed. Warnings are unchanged third-party NumPy/joblib deprecations.

## 10. Not verified

- Real PostgreSQL migration/locking behavior; schema did not change.
- User database contents, signal funnel, training jobs, rejected candidate metrics, model artifacts, fills and outcomes.
- Bybit network/API behavior; not changed.
- Forward profitability or causal explanation of losses.

## 11. Residual risks and limitations

- A valid 2% profile can still be economically unprofitable; risk enforcement limits exposure but does not create edge.
- Rare recommendations may be caused by data freshness, exact decision-candle requirements, spread/EV/RR gates, baseline diagnostics, insufficient training history or quality-gate rejection. Source code alone cannot rank these without runtime diagnostics.
- Historical spread/order-book/funding/fill parity remains partial in research.
- Full walk-forward, drift/regime monitoring, PBO/DSR and forward evidence remain incomplete.

## 12. Rollback procedure

1. Stop API, worker and trainer.
2. Restore the complete 1.9.2 source archive; do not cherry-pick only API or policy files.
3. No DB downgrade is required.
4. Regenerate/recheck release manifest for the restored tree.
5. Be aware that rollback reopens the confirmed profile/global-ceiling bypass; do not activate profiles above global limits.

## 13. Recommended next work package

Implement an auditable decision/training funnel that records, per symbol and hour, the first blocking reason across data freshness, decision candle, spread, scenario geometry, net EV/RR, baseline policy, capital policy and model-quality gates. Pair it with candidate-gate rejection decomposition. This should diagnose “days without recommendations” and “models never pass” from actual data without weakening safety thresholds.
