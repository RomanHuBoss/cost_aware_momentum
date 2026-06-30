# Iteration report — 2026-06-30 — execution economics integrity

## 1. Input and baseline identity

- Input: `cost_aware_momentum-main.zip`.
- Input SHA-256: `cf1db0d0c590c41271a9519e9c5302ea208223b872115c8d0e69170b54e9eac8`.
- Input version: `1.8.16`; output version: `1.8.17`.
- Python requirement: `>=3.12`; check environment: Python 3.13.5.
- Alembic head: `0006_manual_trade_remaining_risk` (six revision files, one head).
- The input archive contained no `.env`, virtual environment, bytecode/cache, database dump or real model artifact. It also omitted root `CHANGELOG.md`, `PATCH_*.md`, `SHA256SUMS` and `docs/INCIDENT_RUNBOOK.md`; those omissions contradicted the attached iteration protocol and some historical release-integrity statements.

## 2. Goal and acceptance criteria

After this iteration the system must present market-signal and execution-plan economics as distinct scopes, calculate break-even with the same three-outcome EV semantics used by policy, and fail closed for corrupted plan snapshots or malformed account-profile modes.

Acceptance criteria:

1. The fixed-`P(TIMEOUT)` break-even threshold independently zeroes `TP/SL/TIMEOUT` EV.
2. API detail preserves capital-independent signal metrics and adds verified plan-snapshot metrics.
3. A non-finite/inconsistent plan snapshot is marked `INVALID_SNAPSHOT` and exposes no trusted plan values.
4. `bybit_read_only` without `source_account_id` and any unknown mode return zero capital and `verified=false`.
5. UI labels both scopes and handles absent break-even values without arithmetic on `null`.
6. Existing API fields remain backward compatible; no migration or new setting is introduced.
7. Full available checks remain green and the release tree is checksum-verifiable.

## 3. Sources and data flow

Read: `README.md`, `pyproject.toml`, `.env.example`, architecture/security/configuration/operator/model documents, QA/compliance/traceability, recent iteration reports, production risk/execution/serializer/frontend modules, tests, and the supplied iterative-development protocol. The embedded specification was inspected for the market-signal/execution-plan boundary and three-outcome EV contract.

Changed flow:

`MarketSignal probabilities/levels` → `risk.math three-outcome rates` → `ExecutionPlan immutable planning entry/cost snapshot` → `API recomputation + integrity check` → `separate signal/plan UI cards`.

Capital flow:

`CapitalProfile mode/account link` → explicit allow-list validation → fresh account snapshot or intentional manual/paper capital → plan sizing; invalid profile state produces zero capital.

## 4. Baseline before edits

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 296 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED — one head `0006_manual_trade_remaining_risk` |
| `python manage.py doctor` | NOT RUN — project-local `.venv`, `.env` and safe PostgreSQL were unavailable |
| `python manage.py test --require-integration` | NOT RUN — no disposable `TEST_DATABASE_URL`; production/user DB was not used |

## 5. Confirmed defects and gaps

### HIGH — binary break-even contradicted production EV

- Location: `app/api/serializers.py`, previous `break_even_probability = 1/(1+signal.net_rr)`.
- Reproduction: for `D=0.02`, `U=0.04`, `T=-0.003`, `P(timeout)=0.20`, the true threshold is `0.276666...`; the binary shortcut is `0.333333...` and does not zero three-outcome EV.
- Impact: operator-facing mathematical misstatement and potentially incorrect interpretation of required TP probability.
- Why tests missed it: no independent EV identity test; serializer asserted only shape/presence.

### HIGH — signal economics was shown beside plan-dependent sizing without plan economics

- Location: `app/api/serializers.py`, `web/js/app.js`.
- Reproduction: a plan recalculated at entry 101 retained signal `net_rr/net_ev_r` calculated at reference entry 100; detail payload exposed no separate plan values.
- Impact: operator could associate qty/status with the wrong entry/cost economics.
- Why tests missed it: no scope-separation contract.

### HIGH — plan economics snapshot lacked presentation-time integrity enforcement

- Location: `ExecutionPlan.sizing_snapshot` → API serializer.
- Reproduction: `net_ev_r='NaN'` was not independently invalidated because plan economics was not rederived/presented.
- Impact: malformed DB/legacy state could be displayed without a clear integrity status.
- Why tests missed it: no corrupted-snapshot serializer test.

### CRITICAL — malformed read-only/unknown profile state fell back to manual capital

- Location: `app/services/execution.py::effective_capital`.
- Reproduction: `mode='bybit_read_only', source_account_id=None` and `mode='legacy-live'` each returned configured `allocated_capital` and could preserve `capital_verified=True` without querying a read-only account snapshot.
- Impact: corrupted/legacy DB state could create an apparently funded plan without the required account binding.
- Why tests missed it: API validation covered normal creation but service-layer tests did not exercise malformed persisted state.

### CONFIRMED DOCUMENTATION GAP

The input archive lacked the root changelog, per-version patch note, incident runbook and checksum manifest required by the supplied iteration protocol. These are release/process gaps, not evidence of a trading defect.

The anonymous reviewer counts could not be validated because no modules, reproductions, traces or expected behavior were supplied. This report does not convert those counts into findings.

## 6. Plan and actual diff

Production:

- `app/risk/math.py`: reusable net outcome rates and exact break-even solver; refactored EV to one shared arithmetic path.
- `app/services/execution.py`: explicit capital mode allow-list; versioned plan-economics snapshot.
- `app/api/serializers.py`: scope separation, recomputation and integrity status.
- `web/js/app.js`: explicit labels/cards and null-safe rendering.

Tests:

- `tests/unit/test_execution_economics_integrity_2026_06_30.py`: seven focused regressions/contracts.
- `tests/unit/test_execution_acceptance_safety.py`: snapshot persistence acceptance test.

Release/docs:

- version sources, `README.md`, `CHANGELOG.md`, `PATCH_1.8.17.md`, QA/compliance/traceability/architecture/model/operator/security documents, incident runbook and this report.
- No ORM, migration, environment-variable or endpoint mutation.

## 7. Red → green evidence

A temporary four-test suite was run against the untouched 1.8.16 tree:

`pytest -q /mnt/data/cam_red_tests/test_red_execution_economics.py` → **4 failed**.

Failures proved: missing execution-plan economics key, unchanged binary threshold, manual-capital fallback for missing read-only account link, and the same fallback for unknown mode.

The identical suite against 1.8.17 → **4 passed**. The maintained focused/acceptance set contains eight tests and passes as part of the full suite. An independent randomized script verified 1,000 three-outcome break-even identities without calling the EV helper as its oracle.

## 8. Migration, API, config and compatibility

- Database migration: none; Alembic head unchanged.
- `.env`: no new or changed variable.
- API: existing signal `net_rr`, `net_ev_r` and `break_even_probability` remain; new fields explicitly expose execution-plan economics and integrity. The legacy break-even alias now has corrected semantics.
- Old snapshots: recalculated when entry/cost inputs are sufficient; otherwise `INVALID_SNAPSHOT` rather than a fabricated fallback.
- Deployment: replace files and restart API/worker.

## 9. Post-change checks

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 304 passed, 4 skipped, 19 warnings |
| focused new/acceptance tests | PASSED — 8 passed |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED — one head `0006_manual_trade_remaining_risk` |
| randomized independent identities | PASSED — 1,000/1,000 |
| release integrity | PASSED — 154/154 after manifest regeneration |
| ZIP integrity/re-extraction | PASSED — `unzip -t`, one root directory and clean re-extraction |

No previously green test regressed.

## 10. Not verified

- PostgreSQL integration tests and migration execution on clean/upgraded databases: no disposable PostgreSQL service/URL.
- `manage.py doctor`: no application `.env`, project-managed `.venv` or safe DB.
- Actual Bybit network/read-only account behavior: intentionally not called from this offline audit.
- Browser interaction beyond JavaScript syntax/static contract: no browser harness.
- Statistical/economic edge, calibration stability, live slippage and forward performance: no fresh OOS/forward dataset supplied.

## 11. Residual risks and limitations

Documented gaps remain: one chronological split rather than full multi-fold walk-forward, no PBO/DSR, incomplete point-in-time universe/spec reconstruction, no historical orderbook or no-fill/partial-fill execution simulator, no live PSI/calibration/performance auto-rollback, and no paper/shadow go/no-go evidence. The strict `1e-12` snapshot equality assumes values were generated by the same Decimal formulas; future economics-schema changes must version and migrate/recompute deliberately.

## 12. Rollback

1. Stop API/worker/trainer.
2. Restore the verified 1.8.16 source release and its matching checksum manifest if available.
3. No database downgrade is needed.
4. Restart and run static/unit checks plus safe PostgreSQL health/integration checks.
5. Plans created by 1.8.17 remain JSON-compatible; 1.8.16 ignores additional snapshot keys. Do not edit audit or plan rows to remove them.

## 13. Recommended next work package

Implement account-scoped portfolio risk and reconciliation invariants end to end: prove whether global aggregation can incorrectly couple independent capital profiles/accounts, then add natural keys/locks/tests and a migration only if the current schema cannot enforce the correct scope. Do not combine that work with walk-forward or drift-monitoring changes.
