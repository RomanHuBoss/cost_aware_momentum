# Iteration report — cost-aware directional selection

## 1. Input and baseline identity

- Input archive: `cost_aware_momentum-main.zip`.
- Input SHA-256: `051e531a1b4aedfbbe7296573158eb673e46205b101408958d2733da634e5045`.
- Input version: `1.8.3`.
- Python requirement: `>=3.12`.
- Alembic head: `0005_plan_outcome_invalid_input`.
- Baseline source counts: 72 production/script/frontend files, 25 test files, 9 documentation files.
- No `.env`, credentials, database dumps or real model artifacts were present in the input archive.

Missing historical Markdown files were not treated as defects. Scope was restricted to reproducible mathematical, logical and econometric behavior.

## 2. Goal and acceptance criteria

Goal: after this iteration, the worker must choose LONG or SHORT by the exact current net `EV/R` calculation used in the published signal and conceptually matched by the holdout policy gate, rather than selecting a direction first with a fixed cost-agnostic model utility.

Acceptance criteria:

1. Runtime exposes both LONG and SHORT `TP / SL / TIMEOUT` distributions.
2. Current bid/ask, fee, slippage, funding and barrier geometry are applied to each direction before selection.
3. The direction with the highest exact net `EV/R` is published.
4. Existing artifact task/classes/features remain compatible.
5. Existing `ModelRuntime.predict()` remains available.
6. A numerical counterexample fails before the fix and passes after it.
7. Full unit/static/frontend checks do not regress.
8. Advisory-only and PostgreSQL-only boundaries remain unchanged.

## 3. Sources and data flow reviewed

Reviewed: `README.md`, `pyproject.toml`, `docs/ARCHITECTURE.md`, `docs/MODEL_CARD.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, risk mathematics, model runtime, training policy evaluation, signal publication, execution planning, outcome evaluation, backtest code and related tests.

Affected data flow:

`hourly features -> ModelRuntime LONG/SHORT probabilities -> current bid/ask and cost scenario -> directional net RR/EV -> selected MarketSignal -> profile-dependent ExecutionPlan -> API/UI`.

The holdout flow was compared independently:

`holdout LONG/SHORT probabilities -> exact configured economics -> max expected EV/R direction -> policy gate -> activation decision`.

## 4. Baseline before changes

Authoritative baseline used an isolated virtual environment outside the project tree with the project installed as `.[dev]`.

- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: `160 passed, 4 skipped, 19 warnings`.
- `node --check web/js/app.js`: PASSED.
- `alembic heads`: `0005_plan_outcome_invalid_input (head)`.

The four skips were PostgreSQL integration tests because `TEST_DATABASE_URL` was not configured. `python manage.py doctor` and `python manage.py test --require-integration` were not used as proof because the repository-local `.venv` and isolated PostgreSQL test database were not configured. An initial host-environment run was non-authoritative and failed on missing project dependencies; it was replaced by the isolated environment above before production edits.

## 5. Confirmed defect

### CONFIRMED DEFECT — high severity

Files/functions:

- `app/ml/runtime.py`, `ModelRuntime._predict_artifact()`;
- `app/ml/training.py`, `evaluate_policy_model()`;
- `app/services/signals.py`, `publish_hourly_signals()`.

Actual behavior in 1.8.3:

1. Runtime computed both directional probabilities internally.
2. Runtime selected one direction with fixed utility `2.20*P(TP) - 1.15*P(SL) - 0.20*P(TIMEOUT)`.
3. Only after this irreversible choice did `publish_hourly_signals()` apply current fees, slippage, funding and exact net `EV/R`.
4. Holdout policy evaluation did the opposite: it calculated net economics for both directions and selected the maximum `expected_ev_r`.

Therefore the auto-activation gate and production worker could evaluate different policies. A candidate could pass policy metrics using one direction while production published the other. The alternative production direction was not examined even when it had higher net `EV/R`.

Numerical proof with ATR 2%, round-trip fee 0.11%, slippage 0.03%, stop-gap reserve 0.10%, zero funding:

- LONG `(P(TP)=.35, P(SL)=.40, P(TIMEOUT)=.25)`: fixed utility `0.2600`, exact net `EV/R = 0.1534963279`;
- SHORT `(P(TP)=.20, P(SL)=.05, P(TIMEOUT)=.75)`: fixed utility `0.2325`, exact net `EV/R = 0.1850803635`.

The old runtime selected LONG although SHORT had the superior published economic outcome. Existing tests checked probability normalization and holdout selection separately, but none asserted that production direction selection used the same economic oracle.

## 6. Change plan and actual diff

Production:

- `app/ml/runtime.py`: added `predict_scenarios()` and scenario-preserving artifact/baseline implementations; retained `predict()` compatibility.
- `app/services/signals.py`: added `SignalScenarioEconomics` and `select_cost_aware_scenario()`; publication now evaluates both directions before choosing.

Tests:

- `tests/unit/test_cost_aware_direction_selection.py`: two independent regression tests.

Version/release documentation:

- `pyproject.toml`, `app/__init__.py`, `README.md`;
- `CHANGELOG.md`, `PATCH_1.8.4.md`;
- `docs/ARCHITECTURE.md`, `docs/MODEL_CARD.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/QA_REPORT.md`;
- this iteration report.

Migrations/config/API:

- no migration;
- no environment variable;
- no database schema change;
- no JSON/API schema change;
- model artifact task, feature order and outcome class order unchanged.

## 7. Red -> green evidence

Red command before production implementation:

`python -m pytest -q tests/unit/test_cost_aware_direction_selection.py`

Result: collection error, `ImportError: cannot import name 'select_cost_aware_scenario'`, exit code 2.

Green targeted command after implementation:

`python -m pytest -q tests/unit/test_cost_aware_direction_selection.py tests/unit/test_runtime_auth_config.py tests/unit/test_training.py`

Result: `22 passed`.

New tests alone: `2 passed`.

The numerical expected `EV/R` values are derived independently from fixed probabilities, ATR geometry and explicit cost assumptions; the test does not use the selector's own output as its oracle.

## 8. Compatibility and rollback

Compatibility:

- existing artifacts load without retraining;
- `ModelRuntime.predict()` remains available for callers outside the publication flow;
- signal and execution-plan database records keep the same fields and types;
- direction may legitimately differ from 1.8.3 because the corrected policy now considers both exact economic scenarios.

Rollback:

1. stop API, worker and trainer;
2. restore the 1.8.3 project files;
3. restart processes;
4. no DB downgrade or `.env` rollback is needed.

## 9. Post-change verification

- `python -m pip check`: PASSED.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q -rs`: `162 passed, 4 skipped, 19 warnings`.
- `node --check web/js/app.js`: PASSED.
- `alembic heads`: one head, `0005_plan_outcome_invalid_input`.
- forbidden Bybit order endpoint/method grep: no matches.
- release manifest and archive checks are recorded after final packaging.

No previously passing test regressed. The two-test increase is exactly the new regression module.

## 10. Not verified

- PostgreSQL integration tests: not executed; no isolated `TEST_DATABASE_URL` was available. Four tests skipped explicitly.
- `manage.py doctor`: not used because repository-local `.venv`, `.env` and PostgreSQL service were not configured.
- live Bybit market-data smoke test: not executed; no network/account evidence was required for this pure policy correction.
- paper/shadow forward performance: not established.

## 11. Residual risks and limitations

- The deterministic baseline remains an uncalibrated operational scaffold; its two scenario distributions are not evidence of predictive skill.
- Holdout policy uses configured generic costs, while production uses current funding and executable prices. This is intentional, but regime-dependent cost stress remains necessary.
- The current funding treatment in planned risk/EV is conservative when funding is favorable; a separate iteration should formally distinguish conservative sizing downside from signed expected funding cash flow.
- Technical consistency does not demonstrate profitability or eliminate model selection bias.

## 12. Recommended next work package

Independently audit funding economics across planned net `EV/R`, stress sizing, counterfactual outcomes and holdout policy. The acceptance test should distinguish signed expected funding cash flow from intentionally conservative downside sizing and verify settlement-count timing for LONG and SHORT.
