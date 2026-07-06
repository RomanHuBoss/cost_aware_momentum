# QA Report

Release: **1.34.2**

Date: **2026-07-06**
Scope: **timezone-stable immutable universe snapshot hashing**

## Environment

- Python: 3.13.5 in an isolated virtual environment.
- Project requirement: Python >=3.12.
- Node syntax check: available.
- Separate PostgreSQL integration database: not configured.
- Input archive: `cost_aware_momentum-main.zip`.
- Input archive SHA-256: `f16026a1c5f8892c2c512faad6006a5533dcb1068b18b0c84d29748efb807970`.
- Source version: 1.34.1.

## Baseline before changes

| Check | Result |
|---|---|
| clean-source inventory | 232 files including manifest; 96 production Python files; 94 test Python files; 5 documentation/specification files; 16 migration revisions |
| input release integrity | PASSED: 231 eligible files and 231 manifest entries |
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED: no broken requirements |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 692 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |

The seven skipped tests require an isolated PostgreSQL integration database.

## Confirmed defect

`persist_universe_selection` hashed `observed_at` and `recorded_at` using their original
ISO-8601 offsets. `validate_universe_eligibility_snapshot_record` rebuilt the hash from
PostgreSQL-returned `TIMESTAMPTZ` values. PostgreSQL may render the same instant in the
session timezone, so semantically identical timestamps generated different hash bytes.

This produced a false immutable-ledger corruption error and blocked the complete trainer
control path before due/recovery evaluation. Severity: **high**. The failure is operationally
complete for training control, while remaining fail-closed rather than creating unsafe
training evidence.

Existing tests missed the defect because they validated the same ORM object without a
session-timezone round trip.

## Red evidence

On unmodified 1.34.1 code, the new regression changed only the timezone representation of
the same two instants from UTC to UTC+03:00:

```text
test_universe_snapshot_hash_is_invariant_to_postgres_session_timezone
FAILED: ValueError: Universe eligibility snapshot record hash mismatch
```

## Implemented correction

- Added a UTC hash timestamp canonicalizer for timezone-aware datetimes.
- Used it in both snapshot persistence payload construction and replay validation payload reconstruction.
- Preserved all policy, coverage, mode, symbol and record hash validation.
- Wrapped replay validation errors with exact snapshot `id`, `mode` and `recorded_at`.
- Added independent regression tests for timezone invariance and corrupt-row diagnostics.

## Post-change checks

| Check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 694 passed, 7 skipped, 62 warnings |
| related trainer/universe/replay suite | PASSED: 48 passed |
| two new regressions together | PASSED: 2 passed |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0016_universe_replay_asof` |

## Environment-dependent checks

| Check | Result |
|---|---|
| PostgreSQL integration tests | SKIPPED: 7 tests; `TEST_DATABASE_URL` unavailable |
| `python manage.py doctor` | NOT RUN: project-local `.venv`, configured `.env` and PostgreSQL were unavailable |
| `python manage.py test --require-integration` | NOT RUN: no isolated PostgreSQL integration database |
| live Windows PostgreSQL session-timezone round trip | NOT RUN |
| real Bybit forward/shadow cycle | NOT RUN |
| economic profitability/causal loss attribution | NOT ESTABLISHED |

## Release boundary

- Database migration: **none**.
- New `.env` settings: **none**.
- HTTP/frontend schema: **unchanged**.
- Model artifact, feature, label and class schema: **unchanged**.
- Quality, activation, risk and capital thresholds: **unchanged**.
- New dependency: **none**.
- Bybit client remains read-only and advisory-only.

## Residual limitations

- A genuine mutation/corruption of policy, decisions, selected symbols, counts or timestamp
  instants still blocks replay and training as intended.
- Historical snapshots manually created outside the worker with nonstandard timestamp/hash
  conventions are not silently repaired.
- The patch restores trainer profiling/control; it does not weaken minimum-history,
  holdout, class-coverage or profitability gates and does not guarantee a candidate will pass.
- This work package does not prove strategy profitability or explain all historical losses.

## Final release verification

- Clean release inventory: 234 files including `SHA256SUMS`.
- Manifest: 233/233 eligible source entries verified.
- ZIP integrity: PASSED.
- Archive structure: one root directory, `cost_aware_momentum-1.34.2`.
- Boundary scan: no `.env`, virtual environment, caches, bytecode, egg-info, build/dist output, dumps, credentials or model artifacts.
- Full suite from an independently re-extracted release: 694 passed, 7 skipped, 62 warnings.
- Re-extracted dependency, compile, Ruff, JavaScript syntax, Alembic single-head and release-integrity checks: PASSED.
