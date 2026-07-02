# Iteration report — 2026-07-02 — research/live parity and release integrity

## 1. Input, hash and version

- Input: `cost_aware_momentum-main.zip`.
- SHA-256: `bcf7787004b257a1dcaf17a792f1291733b6246f0d8fd8b4259d3ff1cd1c4854`.
- Source version: `1.8.31`; result version: `1.8.32`.
- Python requirement: `>=3.12`.
- Initial inventory: 69 production/source files, 48 test files and 14 documentation files by the iteration inventory rules.
- Original release had no `.env`, secret, model artifact or database dump, but it omitted its claimed `SHA256SUMS`, changelog and patch history.

## 2. Goal and acceptance criteria

After this iteration the project must have one deployable Alembic head and research/promotion economics must exclude overlapping same-symbol trades that the live acceptance path would reject.

Acceptance criteria:

1. all Alembic revision IDs fit the standard 32-character version column;
2. `python -m alembic heads` returns exactly `0008_outcome_path_unavailable`;
3. backtest blocks a second trade for one symbol while the prior modeled trade is active;
4. promotion evaluation applies the identical rule and exposes the blocked count;
5. a new trade is permitted exactly at the prior modeled exit boundary;
6. candidate/incumbent policy evidence uses a new explicit schema;
7. full unit/static/frontend checks remain green;
8. release archive has one root, no forbidden runtime artifacts and a verified SHA256 manifest.

## 3. Sources read and affected flow

Read: `README.md`, `pyproject.toml`, `.env.example`, architecture/security/configuration/operator/runbook/model/QA/compliance/traceability documents, all available prior iteration reports, embedded DOCX specification, migration graph, risk/cost services, signal/execution/outcome paths, ML features/labels/training/lifecycle/runtime, trainer/inference workers, Bybit read-only client, API schemas, frontend JS and relevant unit/integration tests.

Affected data flow:

`directional holdout rows → probability and barrier validation → best direction per symbol/time → actionability gate → one-active-symbol filter → cohort/sleeve economics → promotion metrics`

and

`Alembic version files → ScriptDirectory graph → upgrade SQL/version table → release verification`.

## 4. Baseline

Global Python 3.13.5 could compile the project and validate frontend syntax, but lacked project dependencies and had an unrelated MoviePy/Pillow conflict. A clean isolated venv was therefore used for project evidence.

Isolated baseline:

- pip check: passed;
- compileall: passed;
- Ruff: passed;
- pytest: **1 failed, 407 passed, 4 skipped, 19 warnings**;
- node syntax: passed;
- Alembic: **two heads**;
- PostgreSQL integration/doctor: not run because no safe configured PostgreSQL instance existed.

## 5. Confirmed defects and evidence

### CRITICAL — duplicate Alembic 0008 branches

`migrations/versions/0008_outcome_path_unavailable.py` and `0008_plan_outcome_path_unavailable.py` had the same parent and equivalent DDL/backfill. The obsolete ID was 34 characters. The existing length contract failed and Alembic enumerated both as heads. Existing tests checked only length, not head cardinality, so a new graph assertion was added.

### HIGH — research/live active-symbol mismatch

Live acceptance queries active plans by symbol and account scope and rejects another plan in `ACCEPTED`, `ENTERED` or `PARTIAL`. Backtest and promotion evaluation only selected one direction per symbol/timestamp, not one active position across timestamps. A minimal two-row hourly BTC example with exit at `t+2` produced two modeled trades although the second could not be accepted live.

Impact: biased trade rate/count, return, drawdown, concurrency and auto-activation evidence. Existing sleeve accounting limited capital leverage but did not enforce the live position-state constraint, so tests considered the behavior valid.

### HIGH — false release provenance

The source QA document claimed a verified 159-entry manifest and referenced changelog/patch files absent from the supplied archive. This prevented independent verification of the actual tree.

## 6. Plan and actual diff

Production:

- `app/ml/training.py`: shared overlap filter, promotion counters, policy schema v7;
- `scripts/backtest.py`: same filter, corrected counts/rates/returns and output metadata;
- deleted duplicate `migrations/versions/0008_plan_outcome_path_unavailable.py`.

Tests:

- `tests/unit/test_backtest_econometrics.py`: block overlap and allow exact-boundary re-entry;
- `tests/unit/test_quant_integrity_2026_06_29.py`: promotion/live parity;
- `tests/unit/test_migration_revision_contract.py`: exact single-head contract;
- schema fixtures updated from v6 to v7 where they represent current evidence.

Version/release/docs:

- `app/__init__.py`, `pyproject.toml` → 1.8.32;
- `README.md`, `CHANGELOG.md`, `PATCH_1.8.32.md`;
- architecture, model card, configuration, security, runbook, operator, QA, compliance and traceability docs;
- `SHA256SUMS` generated after cleanup.

## 7. Red → green evidence

Before production change, the two modified overlap regression tests failed:

- backtest returned 2 trades instead of 1;
- promotion evaluation returned old v6 schema and counted both hourly same-symbol trades.

After implementation, both passed. Migration baseline had one failing length test and two Alembic heads; after deleting the duplicate branch, both migration tests passed and one head remained. A new boundary test proves that an exit at time `t` releases the symbol before a new entry at the same `t`.

## 8. Migration, API, config and compatibility

No new migration or schema change. The fix removes a duplicate release file and restores the intended head. No API or `.env` contract changed. Policy metrics intentionally move to `exit-time-open-gap-single-symbol-cohort-v7`; current trainer recomputes candidate and incumbent on the same holdout. Legacy v6 evidence cannot silently pass the gate.

## 9. Post-check

- pip check: passed;
- compileall: passed;
- Ruff: passed;
- pytest: **410 passed, 4 skipped, 19 warnings**;
- frontend JS syntax: passed;
- Alembic heads: one expected head;
- offline PostgreSQL SQL generation: passed;
- release tree and manifest: passed — 159 files checked, 159 manifest entries.

## 10. Not verified

- PostgreSQL integration suite and actual upgrade/backfill/downgrade: no safe PostgreSQL server/test database.
- `manage.py doctor`: no operational `.env` or DB service.
- Bybit network smoke: unnecessary for the changed local research/migration paths and not used as evidence.
- Forward profitability, fill realism, exact historical funding/order book, full walk-forward, drift and PBO/DSR.

## 11. Residual risks and limitations

The one-active-symbol filter uses modeled exit time, while manual production closure can be recorded later; therefore research remains optimistic relative to operational delay after an exit signal. Historical execution realism remains partial. Existing active artifacts are not rewritten, and their old stored evidence must not be treated as v7 promotion evidence.

## 12. Rollback

1. Stop trainer/backtest processes.
2. Restore 1.8.31 code only if the duplicate migration file is removed manually and the retained head is `0008_outcome_path_unavailable`; do not restore the defective archive as-is.
3. Revert policy schema/code/tests together; do not mix v6 and v7 promotion metrics.
4. No database downgrade is required because 1.8.32 adds no migration.
5. Keep the active incumbent unchanged during rollback.

## 13. Recommended next work package

Implement a point-in-time historical execution dataset and walk-forward evaluator that includes funding settlement timestamps, entry-zone/no-fill/operator delay and robust multiple-testing controls (including clearly scoped PBO/DSR), without weakening the current fail-closed gates.
