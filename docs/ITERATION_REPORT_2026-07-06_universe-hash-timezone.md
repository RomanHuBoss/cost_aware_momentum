# Iteration report — universe hash timezone stability

## 1. Input

- Archive: `cost_aware_momentum-main.zip`
- SHA-256: `f16026a1c5f8892c2c512faad6006a5533dcb1068b18b0c84d29748efb807970`
- Source version: 1.34.1
- Target version: 1.34.2

## 2. Goal and acceptance criteria

After this iteration, trainer control and training-data profiling must accept an immutable
universe snapshot when PostgreSQL returns the same `TIMESTAMPTZ` instants using a different
session UTC offset, while continuing to reject actual evidence mutation.

Acceptance criteria:

1. Equivalent aware datetime instants hash identically regardless of UTC offset rendering.
2. Existing UTC-produced snapshot hashes remain unchanged.
3. Policy hash, mode, decision coverage and selected-symbol checks remain fail-closed.
4. A genuinely invalid record hash still raises.
5. Invalid-row errors identify the exact snapshot without exposing secrets.
6. No migration, `.env`, API, model artifact or risk-gate change is introduced.
7. Full available checks remain green.

## 3. Sources and data flow

Read: `README.md`, `CHANGELOG.md`, `PATCH_1.34.0.md`, `PATCH_1.34.1.md`,
`pyproject.toml`, `.env.example`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`,
`docs/TRACEABILITY.md`, the relevant dynamic-universe/training sections of the DOCX
specification, and the production/tests listed below.

Affected flow:

`market worker UTC refresh` → `persist_universe_selection` → PostgreSQL `TIMESTAMPTZ` +
immutable JSON evidence → `load_point_in_time_universe_snapshots` →
`validate_universe_eligibility_snapshot_record` → `load_training_market_data` →
`load_training_data_profile` → trainer `current_training_profile`/`due_reason` → control response.

## 4. Baseline

| Command/check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 692 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED: `0016_universe_replay_asof` |
| input `scripts.release_integrity` | PASSED: 231/231 eligible entries |

## 5. Confirmed defect

### HIGH — false immutable record-hash mismatch after PostgreSQL timezone rendering

- Production locations: `app/services/universe.py::_snapshot_payload`,
  `validate_universe_eligibility_snapshot_record`.
- Trigger location: `app/ml/universe_replay.py::load_point_in_time_universe_snapshots`.
- Reproduction: persist a valid UTC snapshot, then represent its two `TIMESTAMPTZ` fields
  as the same instants at UTC+03:00 before validation.
- Expected: the same instants and unchanged evidence validate.
- Actual: hash mismatch because `.isoformat()` encoded different offsets.
- Impact: trainer control/profile/recovery request aborts before gate evaluation.
- Why tests missed it: prior unit tests never changed ORM datetime offset representation
  between persistence and validation.

The user-provided traceback matches this exact call path. No evidence justified weakening
model-quality or minimum-history gates; those remain unchanged.

## 6. Plan and diff

Production:

- `app/services/universe.py`: canonical UTC timestamp representation for record hashing.
- `app/ml/universe_replay.py`: exact invalid-snapshot diagnostics.

Tests:

- `tests/unit/test_universe_eligibility_ledger_2026_07_06.py`
- `tests/unit/test_postgres_native_universe_replay_2026_07_06.py`

Release/docs:

- `pyproject.toml`, `app/__init__.py`, `README.md`, `CHANGELOG.md`
- `PATCH_1.34.2.md`
- `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`
- this report and regenerated `SHA256SUMS`

## 7. Red → green evidence

Red on original source:

```text
1 failed
ValueError: Universe eligibility snapshot record hash mismatch
```

Test:
`test_universe_snapshot_hash_is_invariant_to_postgres_session_timezone`.

Green after correction:

```text
3 passed
```

for the new regression plus the existing hash-bound persistence test and streaming loader
contract. The final two new regressions pass together (`2 passed`), and the wider related
trainer/universe/replay set passes (`48 passed`).

## 8. Migration/API/config compatibility

- Migration: none; head remains `0016_universe_replay_asof`.
- Existing rows: no update/delete and no hash rewrite.
- `.env`: none.
- API/UI: unchanged.
- Artifact/features/labels/classes: unchanged.
- Quality/risk/promotion gates: unchanged.
- Rollback: stop trainer, restore 1.34.1 files, restart trainer. No schema rollback is needed.

## 9. Post-check

| Command/check | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 694 passed, 7 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `python -m alembic heads` | PASSED: one head |

Final release verification: 234 files including `SHA256SUMS`; 233/233 eligible entries
verified; one root directory `cost_aware_momentum-1.34.2`; ZIP integrity passed. An
independently re-extracted release passed pip check, compileall, Ruff, Node syntax, Alembic
single-head, release integrity and the full suite (`694 passed, 7 skipped, 62 warnings`).

## 10. Not verified

- Actual PostgreSQL integration and a Windows PostgreSQL session configured to UTC+03 were
  unavailable.
- `manage.py doctor` and `manage.py test --require-integration` were not runnable without a
  project-local configured environment and isolated PostgreSQL database.
- No real Bybit forward/shadow cycle was run.

## 11. Residual risks

- Genuine corrupt evidence continues to block trainer operation; the new contextual error
  must be investigated rather than bypassed.
- Manually inserted historical rows that did not follow the worker's UTC timestamp contract
  are not automatically rewritten.
- Restored trainer control does not imply sufficient data, gate passage or profitable signals.

## 12. Rollback

1. Stop trainer/API/worker processes using release 1.34.2.
2. Restore release 1.34.1 application files.
3. Restart processes.
4. Do not modify `market.universe_eligibility_snapshots`; no migration was applied.

## 13. Recommended next work package

Add a read-only operator diagnostic command that audits every universe snapshot hash and
classifies timezone-equivalent legacy rows separately from genuine content corruption,
without updating the immutable ledger.
