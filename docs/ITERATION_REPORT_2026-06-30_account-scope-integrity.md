# Iteration report — account/profile scope integrity

## 1. Input and identity

- Input archive: `cost_aware_momentum-main.zip`
- Input SHA-256: `cd1a8751d51410b3e4beebd7630e2321e051ef3089189e294a4bf96ec55d6b3d`
- Input version: `1.8.17`
- Output version: `1.8.18`
- Python requirement: `>=3.12`; checks used Python 3.13.5.
- Baseline Alembic head: `0006_manual_trade_remaining_risk`.
- Initial inventory: 81 production files, 36 test files, 26 documentation files, 152 total files.
- The input tree had no real `.env`, credentials, model artifacts, database dumps or virtual environment. It also lacked `SHA256SUMS`, `CHANGELOG.md` and the patch file referenced by repository history.

## 2. Goal and acceptance criteria

After this iteration, portfolio risk, acceptance serialization, active-symbol conflicts, position snapshots, reconciliation and portfolio display must use one explicit profile/account scope, proven by regression tests and a database migration.

Acceptance criteria:

1. Manual/paper profiles are isolated by `profile_id`.
2. Read-only profiles with the same `source_account_id` share account risk.
3. Missing read-only account identity fails closed.
4. Position snapshots persist account identity and can be queried by account/time.
5. Reconciliation never mixes equity, positions or journal rows from another account/profile scope.
6. Portfolio API and acceptance conflict queries use the same scope semantics.
7. Existing unit suite remains green; migration has one head.
8. Release archive is clean and manifest-verifiable.

## 3. Sources and data flow

Read: README, pyproject, environment template, architecture, QA, specification compliance, traceability, model card, configuration, security, incident runbook, operator manual, recent iteration reports, the attached iteration protocol and the embedded DOCX specification.

Changed data flow:

`CapitalProfile(id/mode/source_account_id)` → scope validation → scoped risk/reconciliation SQL → execution plan acceptance and portfolio API → operator UI.

Read-only ingestion flow:

Bybit private GET → account identity `bybit-unified` → equity and position snapshots with the same `account_id` → account-filtered reconciliation.

## 4. Baseline

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 304 passed, 4 skipped, 19 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — `0006_manual_trade_remaining_risk` |
| `python manage.py release-check` | FAILED — no manifest; runtime caches created by checks were also rejected |
| `python manage.py doctor` | UNAVAILABLE — project-local `.venv` and runtime `.env` absent |
| `python manage.py test --require-integration` | NOT RUN safely — no isolated `TEST_DATABASE_URL`; wrapper also requires project-local `.venv` |

The four skipped tests are PostgreSQL integration tests.

## 5. Confirmed defects

### D1 — global portfolio-risk aggregation — HIGH

`app/services/execution.py::open_risk_usdt` summed all accepted plans and open trades without profile/account predicates. A paper/manual profile could consume another profile's limit; profiles representing one exchange account had no explicit shared-account contract. Existing tests checked arithmetic only, not scope.

### D2 — global acceptance lock — MEDIUM

`load_acceptance_risk_state` used one `execution_risk_accept:global` advisory lock. Unrelated profiles serialized each other and the lock did not express the actual risk invariant.

### D3 — account-ambiguous position snapshots — HIGH

`PositionSnapshot` stored symbol/time/source but no account identity. A position row could not be safely joined to `AccountEquitySnapshot.account_id`.

### D4 — global reconciliation — HIGH

`reconciliation_issues` selected the newest equity snapshot globally, positions only by timestamp, and all open manual trades. This could produce false pass or false block when more than one profile/account existed.

### D5 — unscoped portfolio API — HIGH

`/api/v1/portfolio/risk` aggregated every open manual trade and the newest exchange snapshot globally, despite returning one active profile.

### D6 — unscoped same-symbol acceptance conflict — MEDIUM

One active plan for a symbol blocked all profiles, including unrelated manual/paper profiles.

### D7 — stale integration head assertion — MEDIUM

The PostgreSQL integration test expected revision `0005` while the baseline head was already `0006`; it would fail when integration tests were enabled.

### D8 — incomplete release boundary — MEDIUM

The input omitted `SHA256SUMS`, `CHANGELOG.md` and patch metadata, so release verification failed and repository claims were not reproducible from the archive.

No evidence supported the claim that the archive necessarily contained 38 distinct critical defects. This iteration reports only reproduced or unambiguous defects.

## 6. Change plan and diff

Production:

- `app/services/execution.py`: deterministic scope key/predicate; scoped risk, lock and reconciliation.
- `app/db/models.py`: mandatory `PositionSnapshot.account_id` and account-time index.
- `app/services/market_data.py`: consistent account identity propagation.
- `app/api/v1/recommendations.py`: scope-aware same-symbol conflict.
- `app/api/v1/portfolio.py`: profile/account-filtered journal and exchange state.
- `app/__init__.py`, `pyproject.toml`: version 1.8.18.

Database:

- `migrations/versions/0007_position_account_scope.py`.

Tests:

- new `tests/unit/test_account_scope_integrity_2026_06_30.py`;
- updated acceptance safety, quantitative audit and PostgreSQL migration tests.

Documentation/release:

- README, architecture, QA, compliance, traceability, configuration, security, operator manual;
- `CHANGELOG.md`, `PATCH_1.8.18.md`, this report and regenerated `SHA256SUMS`.

## 7. Red → green evidence

Command:

```bash
python -m pytest -q tests/unit/test_account_scope_integrity_2026_06_30.py
```

Unmodified behavior: **7 failed**. Failures independently showed absent `account_id`, absent scope key and incompatible unscoped function contracts.

After implementation, the expanded module reports **10 passed**. It additionally verifies account-stamped ingestion, fail-closed missing identity and profile-filtered portfolio API behavior.

## 8. Migration and compatibility

- New head: `0007_position_account_scope`.
- Upgrade adds nullable `account_id`, backfills, makes it NOT NULL, then creates `ix_position_account_time`.
- Known connector rows (`source='bybit-read-only'`) backfill to `bybit-unified`; other legacy sources use `legacy-unknown` to avoid false account attribution.
- Downgrade drops the index and column; account identity is lost on downgrade.
- No `.env` changes.
- API response shapes remain compatible; only selected data is correctly scoped.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 314 passed, 4 skipped, 19 warnings |
| focused account-scope module | PASSED — 10 passed |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED — one head, `0007_position_account_scope` |
| offline Alembic upgrade/downgrade SQL generation | PASSED |
| `git diff --no-index --check` equivalent | PASSED — no whitespace errors |
| advisory-only order-surface scan | PASSED — no create/amend/cancel methods or endpoints |
| clean release inspection | PASSED — 157 eligible files, no forbidden artifacts |
| `python manage.py release-check` | PASSED — 157 files / 157 manifest entries |

No previously green test regressed. PostgreSQL integration execution remains unverified without a disposable database.

## 10. Not verified

- Alembic upgrade/downgrade against a real PostgreSQL database.
- Runtime `doctor` against a configured application environment.
- Real Bybit read-only synchronization with credentials.
- Forward paper/shadow economics and profitability.

## 11. Residual risks and limitations

- The connector currently maps one credential set to the stable account identity `bybit-unified`; multiple simultaneous credential sets are not implemented.
- The migration cannot reconstruct account ownership for arbitrary third-party legacy position sources; those rows remain `legacy-unknown`.
- Full multi-fold walk-forward, PBO/DSR, historical point-in-time orderbook/spec data, no-fill/partial-fill simulation, drift controls and forward evidence remain open specification items.
- Technical correctness does not imply positive expected return.

## 12. Rollback

1. Stop API, worker and trainer.
2. Back up PostgreSQL and verify restore capability.
3. Downgrade to `0006_manual_trade_remaining_risk` only if losing `position_snapshots.account_id` is acceptable.
4. Restore 1.8.17 code.
5. Re-run migration-head and reconciliation checks before resuming advisory use.

## 13. Recommended next work package

Implement account-scoped PostgreSQL integration tests with two profiles and two synthetic account identities, covering concurrent acceptance, migration upgrade/downgrade and portfolio/reconciliation isolation in real transactions.
