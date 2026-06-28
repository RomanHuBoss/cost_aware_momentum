# Iteration report — monotonic manual fill chronology

Date: 2026-06-28
Version after iteration: **1.7.12**
Scope: **manual trade close temporal integrity**

## 1. Input archive, SHA-256 and source version

- Input archive: `cost_aware_momentum-main.zip`.
- Input SHA-256: `21311ee6b8a6dacfc12b7c83df90f72c1ae8e871da24783e0b481baecdd33c62`.
- Project root: `cost_aware_momentum-main/`.
- Source version: `1.7.11` in `pyproject.toml` and `app/__init__.py`.
- Python requirement: `>=3.12`.
- Alembic migrations: 5; single head `0005_plan_outcome_invalid_input`.
- Initial counts: 71 production/support files under `app/`, `scripts/`, `web/` plus `manage.py`; 19 test files; 25 documentation files; 138 files total.

Input release boundary findings:

- `cost_aware_momentum.egg-info/` was included and is excluded from the new release.
- `SHA256SUMS` referenced missing root files `CHANGELOG.md` and `PATCH_1.7.11.md`, so the manifest was stale/inconsistent.
- No `.env`, real credentials, real model artifacts or database dumps were found.

## 2. Goal and acceptance criteria

Goal:

> After this iteration, a manual partial/full close must preserve the factual fill chronology, proven by endpoint-level red → green tests and the full available suite.

Acceptance criteria:

1. A close earlier than `ManualTrade.entry_time` returns HTTP 422.
2. A close earlier than the latest persisted fill returns HTTP 422.
3. Rejected chronology does not mutate remaining quantity, P&L, audit/outbox or commit state.
4. Equal timestamps remain valid for multiple fills with identical exchange timestamp precision.
5. Validation occurs while the trade row is locked, before state mutation.
6. No migration, `.env`, public request/response schema or frontend change is introduced.
7. Advisory-only, PostgreSQL-only and existing idempotency/audit boundaries remain unchanged.
8. All available static and unit checks remain green.

## 3. Sources read and affected data flow

Read before editing:

- `README.md`, `pyproject.toml`, `.env.example`;
- `docs/ARCHITECTURE.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`, `MODEL_CARD.md`, `CONFIGURATION.md`, `SECURITY.md`, `INCIDENT_RUNBOOK.md`, `OPERATOR_MANUAL.md`;
- the latest iteration reports for 1.7.8–1.7.11;
- `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`, especially the manual execution, fills, transactional and API sections;
- `app/api/v1/trades.py`, `app/api/schemas.py`, `app/db/models.py`, risk math, idempotency and audit services;
- related unit and PostgreSQL integration tests.

The root `CHANGELOG.md` and `PATCH_*.md` files were absent from the input archive despite stale checksum references, so history was reconstructed from QA and iteration reports.

Affected flow:

```text
POST /api/v1/trades/{id}/close
  -> operator authentication + CSRF
  -> idempotency lookup
  -> SELECT ManualTrade ... FOR UPDATE
  -> read latest Fill.fill_time
  -> chronology validation
  -> gross/net P&L and remaining-qty mutation
  -> append Fill + audit + outbox + idempotency response
  -> one commit
```

## 4. Baseline before changes

Baseline was recorded before production edits.

### Host environment

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | Python 3.13.5 |
| `python -m pip check` | FAILED (external environment) | host `moviepy 2.2.1` requires `pillow<12`; Pillow 12.2.0 is installed |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | Ruff absent from host interpreter |
| `python -m pytest -q` | FAILED (environment/collection) | 8 collection errors because host lacked `psycopg` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0005_plan_outcome_invalid_input (head)` |
| `python manage.py doctor` | NOT RUN by manager | project-local `.venv` absent |
| `python manage.py test --require-integration` | NOT RUN by manager | project-local `.venv` absent |

### Isolated project environment

A virtual environment outside the release tree was installed from `.[dev]`. SQLite and a production database were not used.

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **136 passed, 3 skipped, 19 warnings** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0005_plan_outcome_invalid_input (head)` |

The three skipped tests are PostgreSQL integration tests without `TEST_DATABASE_URL`. The 19 warnings are existing joblib/NumPy 2.5 deprecation warnings.

## 5. Confirmed defect

### CONFIRMED DEFECT — out-of-order manual closes were accepted

- **Severity:** high data-integrity / operational correctness.
- **File/function:** `app/api/v1/trades.py::close_trade`.
- **Actual behavior:** after locking the trade, the endpoint checked status and quantity, then immediately calculated P&L and appended a `Fill`. It did not compare `payload.fill_time` with `trade.entry_time` or previous fills.
- **Minimal reproduction 1:** entry at `2026-06-28T12:00:00Z`, close at `11:59:00Z`; 1.7.11 returned success and reduced remaining quantity.
- **Minimal reproduction 2:** existing partial fill at `14:00:00Z`, new close at `13:59:00Z`; 1.7.11 returned success and appended an out-of-order fill.
- **Expected behavior:** factual close fills must not precede entry or a previously persisted fill. Equal timestamps are valid.
- **Impact:** impossible execution chronology, misleading trade journal, distorted reconciliation and audit interpretation, and potentially incorrect downstream realized-performance analysis.
- **Why existing tests missed it:** there was no manual-trade endpoint test; schema tests only required timezone-aware timestamps and did not have access to trade/fill history.

The defect was reproduced directly against the unchanged endpoint with controlled fake session results; it was not inferred from a hypothetical database state.

## 6. Plan and actual diff

Planned minimal system fix:

1. preserve the existing trade row lock;
2. read the latest persisted fill after acquiring the lock;
3. validate chronology before any mutation;
4. add endpoint-level tests including no-mutation assertions;
5. update only directly affected version and documentation files.

Production/version files changed:

- `app/api/v1/trades.py`;
- `app/__init__.py`;
- `pyproject.toml`.

Tests:

- `tests/unit/test_manual_trade_chronology.py` (new).

Documentation/release:

- `README.md`;
- `CHANGELOG.md` (created because absent from input);
- `PATCH_1.7.12.md` (created);
- `docs/ARCHITECTURE.md`;
- `docs/OPERATOR_MANUAL.md`;
- `docs/QA_REPORT.md`;
- `docs/SPEC_COMPLIANCE.md`;
- `docs/TRACEABILITY.md`;
- this iteration report.

No migration, dependency, config, `.env`, serializer, frontend or API schema file changed.

## 7. Red → green evidence

Tests were added before the production fix.

RED command on 1.7.11 production code:

```bash
python -m pytest -q tests/unit/test_manual_trade_chronology.py
```

RED result:

```text
2 failed, 1 passed
```

Both negative tests failed because no `HTTPException` was raised; the endpoint accepted the impossible timestamps.

GREEN after implementation:

```bash
python -m pytest -q tests/unit/test_manual_trade_chronology.py
```

Result:

```text
3 passed
```

The tests independently verify close-before-entry rejection, close-before-latest-fill rejection, no mutation/commit on rejection, and acceptance of an equal timestamp.

## 8. Migration, API, configuration and compatibility

- Version bump: patch `1.7.11` → `1.7.12`.
- Alembic migration: none; head remains `0005_plan_outcome_invalid_input`.
- `.env`: no additions or changes.
- REST request/response schema: unchanged.
- Frontend: unchanged.
- Existing chronological fills: unchanged.
- Existing out-of-order historical rows: not rewritten automatically.
- Audit close payload: backward-compatible addition of `fill_time`.
- Concurrent close safety: the existing `FOR UPDATE` lock serializes mutations of the same trade; the latest-fill query runs after that lock is acquired.

## 9. Post-check

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | PASSED | no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | all checks passed |
| `python -m pytest -q` | PASSED | **139 passed, 3 skipped, 19 warnings** |
| chronology regression module | PASSED | **3 passed** |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0005_plan_outcome_invalid_input (head)` |
| version consistency | PASSED | package/application `1.7.12` |
| forbidden Bybit order-mutation scan | PASSED | no create/amend/cancel/withdraw endpoint or public method |
| whitespace check | PASSED | no trailing whitespace in changed text files |
| `python manage.py doctor` | NOT RUN by manager | no project-local `.venv`, `.env` or configured PostgreSQL service |
| PostgreSQL integration | NOT RUN | no isolated PostgreSQL server/test database or `TEST_DATABASE_URL` |

## 10. Not verified

- Actual PostgreSQL `FOR UPDATE` serialization with two concurrent close requests.
- Migration upgrade/downgrade run on a real PostgreSQL instance; no migration was introduced.
- Browser smoke test; frontend and response schema were unchanged and JavaScript syntax was checked.
- Detection or repair of historical out-of-order fills already present in an existing database.
- Economic performance or profitability.

## 11. Residual risks and limitations

- Direct SQL/import pipelines can still create out-of-order fills unless they reuse the API contract.
- The database schema has no cross-row temporal constraint; such a constraint would require a trigger or controlled service boundary and was not added in this patch.
- Identical timestamps are intentionally allowed, so ordering between fills at the same timestamp remains insertion/audit order rather than a separate exchange sequence number.
- PostgreSQL concurrency evidence remains necessary before calling the lock behavior integration-tested.

## 12. Rollback procedure

1. Stop the API process.
2. Restore source release 1.7.11.
3. No migration downgrade or `.env` rollback is required.
4. Restart the API.
5. Previously committed 1.7.12 fills remain schema-compatible.

Rollback reintroduces acceptance of out-of-order manual closes.

## 13. Recommended next work package

Add a dedicated PostgreSQL integration test that submits two competing partial closes for one trade, proves row-lock serialization, verifies monotonic persisted fill times and confirms idempotency/audit/outbox rollback on the losing request. This requires an isolated PostgreSQL test database and is intentionally not implemented in this iteration.
