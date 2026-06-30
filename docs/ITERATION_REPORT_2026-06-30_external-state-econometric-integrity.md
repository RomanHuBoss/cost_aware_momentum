# Iteration report — external-state and econometric integrity

## 1. Input and baseline identity

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `410ed60b5d7542a95c3f24b347a172b09930d7a4362f36beb2267e9a81e4fb06`
- Source version: `1.8.18`
- Output version: `1.8.19`
- Python requirement: `>=3.12`; audit interpreter: Python 3.13.5
- Alembic head before and after: `0007_position_account_scope`
- Input tree: 81 production/runtime files, 37 test files, 26 documentation files.
- The input archive lacked the `CHANGELOG.md`, `PATCH_1.8.18.md` and `SHA256SUMS` claimed by its previous internal iteration report. This iteration restores current release artifacts without reconstructing undocumented historical patch files.

## 2. Goal and acceptance criteria

After this iteration, external Bybit state and holdout policy metrics must fail closed rather than silently truncating, fabricating or overstating data.

Acceptance criteria:

1. All position pages are consumed; cursor cycles terminate with an error.
2. Active instrument specs contain only validated exchange values.
3. Wallet and non-zero open positions are valid before any snapshot/write/verification.
4. Missing funding fields block signal, plan and acceptance paths.
5. Bounded intrabar windows persist only complete timestamp sequences.
6. Profit factor with no negative denominator is undefined and fails the existing gate.
7. Advisory-only/PostgreSQL-only/process boundaries and public schema remain unchanged.
8. Full unit suite, static checks, frontend syntax and release manifest pass where the environment permits.

## 3. Sources and data flow

Read: README, architecture/security/configuration/operator/model-card documents, QA/compliance/traceability, prior June 30 reports, risk/execution/signal/market-data/ML modules, Bybit read-only client, ORM models and relevant tests. Official Bybit V5 documentation was checked for position pagination, instrument fields and UNIFIED wallet fields on 2026-06-30.

Changed flows:

- Bybit position GET → cursor validation → complete raw positions → numeric normalization → one account transaction → position/equity snapshots → reconciliation/risk.
- Instruments GET → mandatory field validation → instrument/spec history → signal and sizing constraints.
- Ticker funding → completeness gate → signal economics → plan economics → accept-time revalidation.
- Exact kline window → expected timestamps → upsert → intrabar outcome resolver.
- Holdout exit-event contributions → gains/losses → profit factor → lifecycle quality gate.

## 4. Baseline

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | FAILED — global `moviepy 2.2.1` requires `pillow<12`, sandbox has `pillow 12.2.0`; neither package is a project dependency |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 314 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | NOT RUN successfully — project-local `.venv` and configured `.env` absent |
| `python manage.py test --require-integration` | NOT RUN — no safe disposable PostgreSQL test database |
| `python -m alembic heads` | PASSED — one head, `0007_position_account_scope` |

## 5. Confirmed defects and evidence

### D1 — CRITICAL: truncated read-only positions

- Location: `app/bybit/client.py`, `get_positions`.
- Actual: one request, no `limit`, no cursor continuation; Bybit defaults to 20 rows.
- Expected: all pages before account verification/reconciliation.
- Impact: omitted open positions can understate portfolio exposure and reconciliation discrepancies.
- Existing tests mocked a preassembled list and did not exercise pagination.

### D2 — CRITICAL: fabricated instrument constraints

- Location: `app/services/market_data.py`, `sync_instruments`.
- Actual: missing tick/step/min qty/min notional/leverage were replaced by local constants; missing max qty became unlimited.
- Expected: reject an unverified active specification.
- Impact: invalid price alignment or unsafe order sizing guidance.
- Existing tests did not cover malformed instrument payloads.

### D3 — HIGH: incomplete account data marked verified

- Location: `sync_read_only_account`.
- Actual: absent wallet/position numbers became zero and profiles were marked `capital_verified=True`; validation occurred after partial ORM mutation or not at all.
- Expected: normalize the complete response first and abort before writes.
- Impact: false capital/position state and misleading readiness.

### D4 — HIGH: missing funding treated as zero

- Locations: signal publication, execution-plan construction, acceptance endpoint.
- Actual: `funding_rate or 0` and missing next-settlement timestamp produced zero projected cost.
- Expected: data block until both fields are known.
- Impact: overstated net EV/R and unsafe acceptance under unknown costs.

### D5 — MEDIUM: partial exact candle window reported as success

- Location: `sync_candle_windows`.
- Actual: any non-empty subset was upserted and incremented `windows_succeeded` despite a documented exact-window contract.
- Expected: exact expected timestamp sequence.
- Impact: false diagnostics and repeated/pending outcome reconstruction ambiguity.

### D6 — HIGH: artificial no-loss profit factor

- Location: `app/ml/training.py`, `evaluate_policy_model`.
- Actual: positive gains with zero losses returned `999.0`.
- Expected: undefined ratio (`null`) and fail-closed quality gate.
- Impact: small/one-sided holdout could appear to satisfy economic promotion evidence.

### D7 — MEDIUM: incomplete release history boundary

- Location: input release root.
- Actual: files claimed by the previous report were absent.
- Resolution: current changelog, patch notes, iteration report and manifest are generated; historical files are not invented.

No evidence was available to validate the external claim of 45 specific critical errors. This report counts only reproduced defects.

## 6. Plan and actual diff

Production:

- `app/bybit/client.py`
- `app/services/market_data.py`
- `app/services/signals.py`
- `app/services/execution.py`
- `app/api/v1/recommendations.py`
- `app/ml/training.py`

Tests:

- new `tests/unit/test_external_state_econometric_integrity_2026_06_30.py`
- `tests/unit/test_execution_acceptance_safety.py`
- `tests/unit/test_intrabar_outcomes.py`

Release/docs:

- version sources, README, QA/compliance/traceability/model/security/config/operator/architecture docs
- new `CHANGELOG.md`, `PATCH_1.8.19.md`, this report and `SHA256SUMS`

## 7. Red → green evidence

First unchanged-code run:

`python -m pytest -q tests/unit/test_external_state_econometric_integrity_2026_06_30.py`

Result: 6 failed. Failures independently showed one-page positions, no cursor-loop guard, accepted missing tick, accepted missing equity, partial-window success and `policy_profit_factor == 999.0`.

Second unchanged-code focused run:

`python -m pytest -q tests/unit/test_execution_acceptance_safety.py::test_execution_plan_blocks_missing_funding_snapshot`

Result: 1 failed: actual `ACTIONABLE`, expected `BLOCKED_DATA`.

Green focused runs: 8/8 external-state/econometric tests and the funding regression pass. Two additional positive-path tests cover complete spec persistence and pre-write rejection of a malformed open position.

## 8. Compatibility

- Database migration: none.
- Alembic head unchanged.
- API schema: unchanged.
- `.env`: unchanged.
- Runtime behavior is intentionally stricter: malformed or incomplete external state now blocks.
- Existing artifacts remain readable; newly evaluated no-loss holdouts store null profit factor and cannot auto-pass that gate.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | FAILED — same unrelated global moviepy/pillow conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 323 passed, 4 skipped |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0007_position_account_scope` |
| focused red/green regressions | PASSED — 7 regression tests |
| added positive-path tests | PASSED — 2 tests |
| `python manage.py release-check` | PASSED after clean manifest generation |

## 10. Not verified

- PostgreSQL integration/migration upgrade/downgrade on a disposable database.
- `manage.py doctor` against a configured local installation.
- Live/testnet Bybit smoke with real read-only credentials and more than 20 simultaneous positions.
- Forward paper/shadow economic evidence, calibration stability, drift and profitability.

## 11. Residual risks and limitations

- Single final holdout remains insufficient for robust strategy selection; no multi-fold walk-forward/PBO/DSR.
- Historical instrument specs/orderbook are not reconstructed point-in-time for all training rows.
- REST snapshots can still be delayed during exchange stress; freshness gates reduce but do not eliminate this risk.
- Position snapshots do not implement an OMS/fill lifecycle; execution remains manual/advisory-only.
- Global sandbox package conflict remains outside the project dependency graph.

## 12. Rollback

Stop API/worker/trainer, restore the 1.8.18 source tree, and restart. No database downgrade or environment rollback is needed. Do not copy 1.8.19 `SHA256SUMS` into a rolled-back tree. Rolling back reintroduces the documented fail-open/truncation behavior.

## 13. Recommended next work package

Implement point-in-time freshness/validity bounds for instrument specifications and explicitly prevent stale spec history from being used indefinitely when repeated instrument synchronization fails. This should be a separate iteration with PostgreSQL integration coverage.
