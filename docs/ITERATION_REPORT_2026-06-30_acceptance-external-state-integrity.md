# Iteration report — acceptance external-state integrity

## 1. Input archive and initial state

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `8f35603d116069e18bd8b1b3dddac83dbbdf2f052557f92457bdf9b9749338cd`
- Initial version: `1.8.19`
- Output version: `1.8.20`
- Python requirement: `>=3.12`; verification interpreter: Python 3.13.5 in `/mnt/data/cam_audit_venv`
- Initial Alembic head: `0007_position_account_scope`
- Initial inventory: 81 production files, 38 test files, 27 documentation files, 7 migrations.
- The input archive contained no `.env`, secrets, virtual environment, caches, dumps or model artifacts.
- Repository-history conflict: the previous iteration report stated that `CHANGELOG.md`, `PATCH_1.8.19.md` and `SHA256SUMS` had been created, but they were absent from the supplied archive. Actual archive contents were treated as authoritative; this release recreates the release-history/manifest boundary without inventing a missing 1.8.19 patch file.

## 2. Goal and acceptance criteria

After this iteration, an execution plan can reach `ACCEPTED` only when the current external state still proves the stored size safe. This is confirmed by deterministic regression tests and the full available suite.

Acceptance criteria:

1. incomplete current funding metadata cannot be treated as zero cost;
2. read-only account reconciliation is repeated before acceptance inside the account-risk transaction;
3. current positive finite 24-hour turnover is required and its `0.0001` fraction limits notional;
4. a missing turnover snapshot blocks plan construction instead of removing the liquidity cap;
5. changed external inputs return HTTP 409 and supersede the mutable old plan;
6. valid zero funding and sufficient current liquidity still allow acceptance;
7. advisory-only, PostgreSQL-only and existing API/database contracts remain unchanged.

## 3. Sources read and affected data flow

Read before modification:

- `README.md`, `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- recent `docs/ITERATION_REPORT_*.md` files;
- `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`, especially the requirement that acceptance recheck current price, market/account freshness, margin, min order and portfolio caps in one transaction;
- risk/cost math, execution-plan construction, recommendation acceptance, read-only reconciliation, market-data models and related unit/integration tests.

Affected flow:

```text
TickerSnapshot(turnover/funding/bid/ask) + account snapshots/manual journal
  -> freshness and account-scoped risk lock
  -> account reconciliation + funding completeness + liquidity-cap derivation
  -> current spec/risk/margin/economics validation
  -> ACCEPTED or HTTP 409 + SUPERSEDED + recalculated plan
  -> OperatorDecision context/audit/outbox
```

## 4. Baseline before changes

Executed from the extracted 1.8.19 root in the isolated environment:

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 323 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | NOT RUN — project-local `.venv` and application `.env` were not configured |
| `python manage.py test --require-integration` | NOT RUN — no disposable PostgreSQL test database was available |

The 19 warnings are joblib/NumPy deprecations in runtime artifact tests, not test failures.

## 5. Confirmed defects and evidence

### D1 — incomplete current funding silently became zero

- Classification: `CONFIRMED DEFECT`, severity **high**.
- Location before fix: `app/api/v1/recommendations.py`, `accept_recommendation()`.
- Trigger: `ticker.funding_rate is None` and/or `ticker.next_funding_time is None` during acceptance.
- Previous behavior: `ticker.funding_rate or 0` plus the no-settlement branch produced zero projected funding and returned HTTP 200 `ACCEPTED`.
- Expected behavior: current funding metadata must be complete or acceptance must fail closed.
- Impact: understated cost and potentially overstated net R/R/EV.
- Existing tests covered adverse funding changes but not missing current metadata.

### D2 — account reconciliation was not repeated at acceptance

- Classification: `CONFIRMED DEFECT`, severity **high**.
- Locations: `create_execution_plan()` performed `reconciliation_issues()`, while `accept_recommendation()` did not.
- Trigger: exchange positions/journal diverge after plan construction but before operator acceptance.
- Previous behavior: the API could accept using only internally recorded open risk and a fresh equity snapshot.
- Expected behavior: unknown/mismatched exchange positions must block acceptance under the same account-scoped transaction.
- Impact: portfolio exposure could be understated.
- Existing tests covered profile/account scoping but not the plan-build-to-acceptance state transition.

### D3 — current liquidity deterioration did not invalidate acceptance

- Classification: `CONFIRMED DEFECT`, severity **high**.
- Locations: turnover cap was computed in `create_execution_plan()` but absent from `validate_execution_plan_for_acceptance()`.
- Trigger: current `turnover_24h × 0.0001` falls below the stored plan notional.
- Previous behavior: HTTP 200 `ACCEPTED` despite the current policy cap being smaller.
- Expected behavior: current notional must be checked against current turnover-derived capacity.
- Impact: stale sizing could exceed the project’s own market-impact/liquidity policy.

### D4 — missing turnover disabled the liquidity cap

- Classification: `CONFIRMED DEFECT`, severity **high**.
- Location before fix: `create_execution_plan()` converted missing/zero turnover to `liquidity_cap=None`.
- Trigger: `ticker.turnover_24h` missing or zero.
- Previous behavior: the plan could remain `ACTIONABLE` because `None` meant “no liquidity limit”.
- Expected behavior: inability to prove liquidity is a data block, not unlimited liquidity.
- Impact: fail-open sizing under incomplete market data.

The unsubstantiated external claim of “20 + 18 critical errors and 7 medium errors” cannot be verified because no modules, reproductions or evidence were supplied. This iteration records only defects reproduced against the provided archive. Severity is not inflated merely to match an anonymous count; the application remains advisory-only and does not submit orders.

## 6. Plan and actual file diff

Production:

- `app/services/execution.py` — shared Decimal-safe liquidity-cap function; plan-build block; acceptance validation field/check.
- `app/api/v1/recommendations.py` — funding completeness, repeated reconciliation, current liquidity derivation, audit context.

Tests:

- `tests/unit/test_execution_acceptance_safety.py` — four red/green regressions and six exact/boundary cases.

Version/release/docs:

- `app/__init__.py`, `pyproject.toml`, `README.md`;
- `CHANGELOG.md`, `PATCH_1.8.20.md`;
- `docs/ARCHITECTURE.md`, `SECURITY.md`, `OPERATOR_MANUAL.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `QA_REPORT.md`;
- this iteration report and regenerated `SHA256SUMS`.

One unrelated pre-existing trailing-space defect in `docs/ITERATION_REPORT_2026-06-29_execution-acceptance-safety.md` was normalized solely so the release whitespace check could pass; its semantic content was not changed.

## 7. Red → green evidence

Red command on unchanged production code after adding the four focused regressions:

```text
python -m pytest -q \
  ...::test_acceptance_recalculates_when_current_funding_snapshot_is_incomplete \
  ...::test_acceptance_recalculates_when_account_reconciliation_is_not_clean \
  ...::test_acceptance_recalculates_when_current_liquidity_cap_is_too_low \
  ...::test_execution_plan_blocks_missing_liquidity_snapshot
```

Red result: **4 failed**. The three acceptance tests received HTTP 200 instead of 409; the construction test received `ACTIONABLE` instead of `BLOCKED_DATA`.

Green result after production changes: **4 passed**. The complete focused module then passed **30 tests**. Six additional tests independently verify `1,000,000 × 0.0001 = 100` and rejection of `None`, zero, negative, `NaN` and infinity.

## 8. Migration, API, config and compatibility

- Alembic migration: none; head remains `0007_position_account_scope`.
- `.env` variables: none added or changed.
- Public request/response schema: unchanged.
- Existing mutable-plan conflict behavior remains HTTP 409 with recalculation; decision context gains an internal audit field.
- Advisory-only boundary preserved: no create/amend/cancel/order or withdrawal endpoint was added.
- PostgreSQL remains the only state store.

## 9. Post-change verification

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 333 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0007_position_account_scope (head)` |
| text whitespace scan | PASSED after normalization noted above |
| release-tree verification | `PASSED — 160/160 files` |

No previously green test regressed. Version sources agree on 1.8.20.

## 10. Not verified

- PostgreSQL integration tests and migration upgrade/downgrade on a disposable database.
- `manage.py doctor` against a configured installation.
- Real Bybit read-only smoke, including a position/journal mismatch during an operator acceptance race.
- Whether the current turnover fraction `0.0001` is economically optimal for every symbol/regime; this iteration enforces the existing policy consistently rather than claiming it is calibrated.
- Forward paper/shadow profitability, calibration stability, drift, PBO/DSR and live market impact.

## 11. Residual risks and limitations

- Instrument specifications do not yet have an explicit maximum validity age; the latest historical row may remain usable after repeated synchronization failure.
- REST turnover/top-of-book can become stale between validation and manual exchange entry; the system is advisory-only and cannot guarantee fill quality.
- Reconciliation compares snapshots and the manual journal, not an OMS/fill lifecycle.
- Liquidity remains a coarse turnover proxy; no historical orderbook, depth VWAP or empirical impact model is implemented.
- Single final holdout remains insufficient evidence for strategy selection or profitability.

## 12. Rollback procedure

Stop API, worker and trainer; restore the 1.8.19 source tree; restart all processes. No database downgrade or `.env` rollback is required. Recreate/verify the manifest for the restored tree rather than retaining the 1.8.20 `SHA256SUMS`. Rollback reintroduces the documented acceptance fail-open behavior.

## 13. Recommended next work package

Add point-in-time validity/freshness bounds for instrument specification history and fail closed when repeated specification synchronization leaves only an expired row. Cover clean PostgreSQL upgrade/current-row queries and acceptance behavior in a disposable integration database. Do not combine that work with walk-forward/PBO/DSR or historical orderbook modeling in the same iteration.
