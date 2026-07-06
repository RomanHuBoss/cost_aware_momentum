# Iteration Report — Funding Policy Alignment

Date: 2026-07-06  
Release: 1.34.1  
Scope: promotion-bound market-signal funding semantics

## 1. Input archive and source identification

- Input: `cost_aware_momentum-main.zip`
- SHA-256: `980df85007b83468b7b2786414b2a69f857a06f9e414d6d1c131b8d260b4d0b5`
- Source version: 1.34.0
- Python requirement: >=3.12
- Migration revisions: 16
- Alembic head: `0016_universe_replay_asof`
- Eligible source inventory before changes: 227 files; 101 production; 93 test Python; 6 documentation/specification; 16 migrations.

The input release tree was not clean: 19 cache/bytecode/egg-info roots were present. `SHA256SUMS` listed 259 paths while only 227 eligible files existed; 32 paths, including `CHANGELOG.md` and previous reports, were absent.

## 2. Iteration goal and acceptance criteria

**Goal:** after this iteration, the live market-signal direction must use exactly the expected-funding semantics evaluated by final-holdout promotion, while current funding remains a conservative execution/acceptance overlay.

Acceptance criteria:

1. A non-zero expected-funding overlay is rejected by the market-signal selector.
2. `publish_hourly_signals` passes zero funding to directional ranking even when the current ticker rate is non-zero.
3. The current projected funding remains recorded as explicit evidence, not silently discarded.
4. `create_execution_plan` and acceptance continue to recompute fresh funding and fail closed on deterioration.
5. No model gate, risk threshold, migration, `.env`, public API, or artifact schema is weakened or changed.
6. The full available suite remains green and the release is rebuilt without stale or forbidden artifacts.

## 3. Sources reviewed and affected data flow

Reviewed:

- current user request and iterative-work master prompt;
- `README.md`, `PATCH_1.34.0.md`, `pyproject.toml`, `.env.example`;
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`;
- embedded `docs/source/Cost_aware_hourly_ML_momentum_specification.docx` sections on OOS economics, funding, signal/policy separation, and execution plans;
- training, lifecycle, promotion, signal publication, risk math, execution-plan and acceptance modules;
- related unit and PostgreSQL integration tests.

`CHANGELOG.md`, `docs/ARCHITECTURE.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`, and `docs/MODEL_CARD.md` were absent from the actual input tree. Their absence was not concealed or reconstructed as historical evidence.

Affected flow:

```text
candidate final holdout
  -> evaluate_policy_model(expected funding = 0)
  -> quality gate + immutable promotion binding(funding_rate_override = 0)
  -> active artifact
  -> live directional predictions
  -> market-signal selector(expected funding = 0)
  -> persisted market signal
  -> profile-specific execution plan(fresh ticker funding)
  -> acceptance(fresh funding revalidation)
```

## 4. Baseline before modification

Environment: Python 3.13.5 isolated virtual environment; Node available; isolated PostgreSQL unavailable.

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no compile errors |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | 691 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |
| `python -m alembic heads` | PASSED | one head: `0016_universe_replay_asof` |
| input release-integrity verification | FAILED | 19 forbidden roots; 32 missing manifest entries |

The seven skipped tests require an isolated PostgreSQL `TEST_DATABASE_URL`.

## 5. Confirmed defects and evidence

### 5.1 Critical — deployed direction used a policy input absent from promotion evidence

**Classification:** CONFIRMED DEFECT  
**Severity:** critical  
**Modules:** `app/ml/training.py`, `app/ml/lifecycle.py`, `app/services/model_promotion.py`, `app/services/signals.py`

Training metrics explicitly declared no historical point-in-time expected-funding forecast. The lifecycle gate required this declaration, and normal promotion bound `funding_rate_override=0`. Live publication nevertheless calculated current projected funding and passed it into `select_cost_aware_scenario` before LONG/SHORT ranking.

Minimal reproduction on release 1.34.0 with equal directional predictions, bid=ask=last=100, ATR=2%, and no fee/slippage/gap cost:

```text
funding=0 direction=LONG net_ev_r=0.639130434782608695652173913043478261 net_rr=1.91304347826086956521739130434782609
funding=0.005 direction=SHORT net_ev_r=0.639130434782608695652173913043478261 net_rr=1.91304347826086956521739130434782609
```

Expected behavior: live direction must match the policy evaluated and approved on the final holdout.  
Actual behavior: a current funding overlay absent from holdout evidence could reverse the selected direction.  
Impact: promotion statistics did not describe the deployed decision rule, invalidating the econometric interpretation of activation evidence.

Existing tests verified cost-aware selection and execution funding independently, but did not assert that the live publication layer preserves the immutable promotion funding binding.

### 5.2 High — input release boundary and checksum manifest were invalid

**Classification:** CONFIRMED DEFECT  
**Severity:** high for release reproducibility; not a trading-logic defect

The archive contained caches, bytecode and egg-info. Its manifest had 259 entries but 32 referenced absent files. This was corrected as a mandatory release-packaging action, not treated as a second strategy work package.

### 5.3 Observed behavior not “fixed” without evidence

Candidates trained on roughly one day of data failing history/final-holdout gates is consistent with existing fail-closed minimum-support requirements. No gate was relaxed. Rare recommendations can also arise from cost, risk, liquidity, drift and evidence gates; this iteration does not claim a causal explanation for all attrition or losses.

## 6. Change plan and actual diff

Production:

- `app/ml/training.py`: shared `POLICY_EXPECTED_FUNDING_SOURCE` constant.
- `app/ml/lifecycle.py`: lifecycle validation uses the shared constant.
- `app/services/signals.py`: zero promotion-bound funding in market selection; non-zero overlays rejected; current projection retained as execution evidence.
- `app/__init__.py`, `pyproject.toml`: patch version 1.34.1.

Tests:

- `tests/unit/test_signal_policy_funding_alignment_2026_07_06.py`: selector rejects an unvalidated non-zero expected-funding overlay.
- `tests/unit/test_quant_integrity_2026_07_02.py`: live publisher supplies zero selector funding despite a non-zero ticker rate.

Documentation/release:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.34.1.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/ITERATION_REPORT_2026-07-06_funding-policy-alignment.md`
- rebuilt `SHA256SUMS`

No migration, config, frontend, API, model artifact, feature or label change was required.

## 7. Red → green evidence

Before production modification, the new/extended regressions failed for the intended reasons:

```text
test_market_signal_policy_rejects_unvalidated_expected_funding_overlay
Failed: DID NOT RAISE ValueError

test_signal_policy_uses_the_exact_model_atr_without_hidden_clipping
AssertionError: Decimal('0.001') != Decimal('0')
```

After correction:

```text
2 passed in 2.82s
```

A related policy/lifecycle/execution selection set also passed:

```text
106 passed, 38 warnings in 4.07s
```

## 8. Migration, API, config and compatibility

- Migration: none; head remains `0016_universe_replay_asof`.
- `.env`: no new or changed variable.
- Public HTTP/frontend schema: unchanged.
- Database schema: unchanged.
- Model artifact/features/labels/classes/horizon: unchanged.
- Existing active artifact: remains loadable; no retraining required solely for this patch.
- Runtime action: restart inference worker and API so the corrected policy layer is loaded.
- Advisory-only/PostgreSQL-only/process separation: preserved.

Behavioral compatibility is intentionally stricter: direct callers that inject non-zero expected funding into the market selector now receive `ValueError` rather than silently deploying an unevaluated direction policy. Current funding belongs in the execution layer.

## 9. Post-change verification

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | no compile errors |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | 692 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED | syntax valid |
| `python -m alembic heads` | PASSED | one head: `0016_universe_replay_asof` |
| trailing-whitespace scan | PASSED | zero findings |
| production Bybit mutation scan | PASSED | no order create/amend/cancel path |

## 10. Not verified

- PostgreSQL integration tests and migration execution: isolated PostgreSQL unavailable.
- `manage.py doctor`: wrapper requires a project-local `.venv`; project `.env`, PostgreSQL server and PostgreSQL CLI were unavailable.
- `manage.py test --require-integration`: not run without an isolated integration database.
- Real Bybit paper/shadow/forward cycle: not run.
- Historical point-in-time funding forecast quality: data/product does not exist in the repository.
- Profitability and causal attribution of prior losses: not established by unit tests or this patch.

## 11. Residual risks and limitations

1. Zero expected funding is honest and reproducible but may be conservative or incomplete; a future forecast policy requires versioned historical snapshots, leakage-safe evaluation and a new promotion binding.
2. Execution plans may become `NO_TRADE` even when a market signal exists because funding/account/liquidity/risk evidence is intentionally stricter.
3. One-day candidate training remains insufficient for existing minimum-support gates.
4. PostgreSQL concurrency, append-only audit, outbox and acceptance revalidation were covered only by existing unit/static evidence in this environment.
5. This correction eliminates one critical deployment mismatch; it does not validate the user-reported counts of 15/8 critical defects or 4 medium defects.

## 12. Rollback procedure

1. Stop API, inference worker and trainer.
2. Restore the previous 1.34.0 application files; no database downgrade is required.
3. Restart processes and verify active artifact registry state is unchanged.
4. Do not copy the 1.34.1 selector tests into 1.34.0, because they intentionally fail on the old behavior.

Rollback restores the known mismatch and is therefore appropriate only for emergency operational recovery, not as a permanent policy choice.

## 13. Recommended next work package

Implement an attrition/loss attribution report that joins every hourly candidate opportunity to the first terminal blocker (`model gate`, `signal economics`, `drift`, `data freshness`, `liquidity`, `capital/risk`, `operator outcome`) and realized forward counterfactual outcome without leaking future data into decisions. This should be a separate iteration and must not relax any gate before the attribution evidence exists.

## 14. Release archive verification

The clean tree contains 232 files including `SHA256SUMS`; all 231 eligible source entries are listed and verified. ZIP integrity passed, the archive has one root directory (`cost_aware_momentum-1.34.1`), and no forbidden release artifacts were found. After independent re-extraction, dependency, compile, Ruff, JavaScript syntax, Alembic single-head and release-integrity checks passed; pytest reported 692 passed, 7 skipped and 62 warnings.
