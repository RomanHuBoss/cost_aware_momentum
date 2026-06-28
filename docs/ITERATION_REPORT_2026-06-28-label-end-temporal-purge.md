# Iteration report — label-end-aware temporal purge

## 1. Input archive and baseline identity

- Input: `cost_aware_momentum-main(1).zip`.
- Input SHA-256: `d68133e676485d2597a96bffd6e2388a9f4677f0be19be6587ba98b0581bbdf1`.
- Source version: `1.7.9` from `pyproject.toml` and `app/__init__.py`.
- Python requirement: `>=3.12`; verification environment: Python 3.13.5.
- Alembic revisions: `0001` through `0005`; single head `0005_plan_outcome_invalid_input`.
- Initial tree: 66 Python production files under `app/` and `scripts/`, 19 Python test files, 21 Markdown files under `docs/`.
- Release-boundary findings: the input archive contained `cost_aware_momentum.egg-info/` and a pre-existing `SHA256SUMS`; it did not contain the `CHANGELOG.md` or historical `PATCH_*.md` files referenced by prior reports. No `.env`, credentials, dumps, virtual environment, database file, or real model artifact was found.
- No separate DOCX technical specification was supplied in this iteration; the uploaded master prompt and repository documents were used.

## 2. Goal and acceptance criteria

Goal: after this iteration, the ML temporal split must prevent a sample's future barrier-label data from crossing into calibration or final holdout even when observed hourly candles are missing or irregular, proven by deterministic regression tests and a full static/unit post-check.

Acceptance criteria:

1. Every generated LONG/SHORT label records its actual final future-candle timestamp.
2. Train rows are accepted only when `label_end_time` is earlier than the calibration boundary.
3. Calibration rows are accepted only when `label_end_time` is earlier than the final-holdout boundary.
4. The existing horizon-hour post-boundary embargo remains in force.
5. Missing, invalid, or non-forward label timestamps fail closed.
6. Whole timestamp/symbol/direction groups remain unsplit.
7. Artifact metadata identifies the new split semantics without changing the scheduler meaning of `training_end`.
8. No migration, API, `.env`, advisory-only, PostgreSQL-only, or process-boundary change is introduced.

## 3. Sources read and affected data flow

Read before modification: `README.md`, `pyproject.toml`, `.env.example`, all current architecture/QA/compliance/traceability/model/security/operator/runbook documents, the latest iteration reports, ML training/lifecycle/data-profile modules, trainer scheduling code, backtest code, label code, and all relevant unit tests.

The input release had no `CHANGELOG.md` or `PATCH_*.md`; this conflict with previous reports was recorded rather than silently treated as present.

Affected flow:

```text
confirmed hourly PostgreSQL candles
→ point-in-time features at open_time
→ future N-bar TP/SL/TIMEOUT label
→ explicit label_end_time
→ label-end purge + horizon-hour embargo
→ train / calibration / final holdout
→ candidate/incumbent metrics and quality gate
→ immutable artifact metadata
```

## 4. Baseline before changes

The first host run was preserved as an environment result: `ruff` and `psycopg` were unavailable, pytest stopped during collection, and global `pip check` reported an unrelated `moviepy 2.2.1` / `pillow 12.2.0` conflict. No project code was changed before this run.

Declared dependencies were then installed into `/mnt/data/cam_iter_venv`, outside the release tree, and the reproducible baseline was rerun:

| Command | Status |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 131 passed, 3 skipped, 20 warnings |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |
| `python manage.py doctor` | FAILED (environment) — project-local `.venv`/native runtime not configured |
| PostgreSQL integration | NOT RUN at baseline — no separate test database / `TEST_DATABASE_URL` |

## 5. Confirmed defect

### CONFIRMED DEFECT — fixed-hour purge can be shorter than the label window

- Severity: high, ML temporal correctness and unsafe auto-activation risk.
- Files/functions: `app/ml/training.py::make_barrier_dataset` and `chronological_split`.
- Actual 1.7.9 behavior: labels used the next N observed bars, but split boundaries subtracted/added `pd.Timedelta(hours=N)` and did not store the timestamp of the last bar used by each label.
- Minimal reproduction: 420 timestamps spaced four hours apart, eight-bar labels ending 32 hours after feature time, and `purge_rows=8`.
- Observed leakage: the latest selected train label ended at `2025-02-19 20:00 UTC`; the earliest calibration feature began at `2025-02-19 08:00 UTC`.
- Expected behavior: all train labels end strictly before calibration features, and all calibration labels end strictly before holdout features.
- Impact: future OHLC from the next window could enter fitting/calibration, making log loss, Brier, policy metrics, incumbent comparison, and auto-activation gates optimistically biased.
- Why tests missed it: the existing split test used perfectly contiguous one-hour timestamps and asserted only timestamp grouping/counts, not label-window endpoints.

### DOCUMENTED LIMITATIONS

- The project still uses one chronological split, not multi-fold walk-forward/OOF aggregation.
- Training labels still use conservative hourly ambiguity rather than intrabar reconstruction.
- This patch does not add a complete continuity gate for all feature lookback windows.

## 6. Planned and actual diff

Production:

- `app/ml/training.py`
  - add `label_end_time` to generated barrier rows;
  - validate temporal columns fail-closed;
  - purge by actual label endpoint;
  - preserve post-boundary embargo;
  - expose `label_end_time` in holdout metadata.
- `app/ml/lifecycle.py`
  - record `temporal_split_schema=label-end-purged-v2`;
  - record `label_data_end` separately;
  - preserve existing `training_end` scheduler semantics.

Tests:

- `tests/unit/test_training.py`
  - assert generated label endpoints;
  - add sparse-timestamp leakage regression;
  - add missing/invalid endpoint fail-closed test;
  - retain whole timestamp group checks.

Release/docs:

- version sources, `README.md`, `CHANGELOG.md`, `PATCH_1.7.10.md`;
- `docs/ARCHITECTURE.md`, `MODEL_CARD.md`, `QA_REPORT.md`, `SPEC_COMPLIANCE.md`, `TRACEABILITY.md`;
- this iteration report.

Migrations/API/config:

- no migration;
- no API/schema field change;
- no `.env` variable;
- no Bybit client or execution behavior change.

## 7. Red → green evidence

RED command on unmodified 1.7.9 production code after adding regression assertions:

```text
python -m pytest -q \
  tests/unit/test_training.py::test_chronological_split_purges_by_actual_label_end_time \
  tests/unit/test_training.py::test_barrier_dataset_creates_long_and_short_scenarios
```

Essential result:

```text
2 failed
train label end: 2025-02-19 20:00 UTC
calibration start: 2025-02-19 08:00 UTC
'label_end_time' missing from generated dataset
```

GREEN after implementation:

```text
python -m pytest -q tests/unit/test_training.py
8 passed
```

The oracle is independent: the test constructs open/end timestamps explicitly and compares selected split indexes against those timestamps; it does not reuse production split calculations.

## 8. Compatibility and rollback risk

- Version type: patch, `1.7.10`.
- Database: unchanged; head remains `0005_plan_outcome_invalid_input`.
- API/frontend: unchanged.
- Config/env: unchanged.
- Existing artifacts remain immutable and retain their previous metrics. New artifacts are distinguishable by `temporal_split_schema` and `label_data_end`.
- `training_end` remains the latest eligible feature timestamp because trainer scheduling and current data-profile comparison rely on that contract.
- Behavior change: a sparse dataset can produce fewer train/calibration samples or fail the minimum-window check instead of training with overlapping labels. This is intentional fail-closed behavior.

## 9. Post-check

| Command | Status |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED — No broken requirements found |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 133 passed, 3 skipped, 19 warnings |
| `python -m pytest -q tests/unit/test_training.py` | PASSED — 8 passed |
| `node --check web/js/app.js` | PASSED |
| `alembic heads` | PASSED — `0005_plan_outcome_invalid_input` |
| `python manage.py doctor` | FAILED (environment) — project-local `.venv`, `.env`, PostgreSQL tools/service not configured |
| `python -m pytest -q tests/integration_postgres -rs` | SKIPPED — 3 tests; `TEST_DATABASE_URL` not configured |

Release checks are recorded after final archive construction below.

## 10. Not verified

- PostgreSQL migration/audit/concurrency execution against a real separate PostgreSQL server.
- Native Windows runtime and `manage.py doctor` with a project-local `.venv`.
- Real trainer cycle on production-scale sparse market history.
- Economic impact on out-of-sample performance or profitability.
- Full multi-fold walk-forward, feature drift, or live forward evidence.

## 11. Residual risks

- Feature rolling calculations can still span data gaps; this patch protects split boundaries but does not certify feature-history continuity.
- A single final holdout remains sensitive to regime selection.
- Historical artifacts produced before 1.7.10 do not gain the new semantics automatically.
- Smaller sparse datasets can now fail minimum-window requirements, requiring history repair/backfill rather than a relaxed gate.

## 12. Rollback procedure

1. Stop trainer, worker, and API.
2. Restore 1.7.9 code/docs; no database downgrade is required.
3. Existing 1.7.10 artifacts may remain on disk, but do not activate them with older code unless their bundle compatibility has been reviewed.
4. Restore the previously active model registry version if it was changed operationally.
5. Restart processes and verify readiness.

Rollback reintroduces the documented sparse-history leakage risk; prefer fixing/backfilling data rather than reverting.

## 13. Recommended next work package

Add point-in-time continuity validation for the full feature lookback and label horizon per symbol, with explicit diagnostics for missing hourly bars. Keep that separate from multi-fold walk-forward and intrabar label reconstruction.

## 14. Release validation

Final release-tree composition before checksums:

- 132 regular files;
- 77 production/support files under `app/`, `scripts/`, `web/`, and `migrations/`;
- 66 Python production files under `app/` and `scripts/`;
- 19 test files;
- 23 documentation files under `docs/`;
- one root directory: `cost_aware_momentum-1.7.10-label-end-temporal-purge/`.

Final validation performed after packaging:

- generated `SHA256SUMS` for the release tree and verified it with `sha256sum -c`;
- `unzip -t` completed without errors;
- re-extracted the ZIP into a new clean directory and verified the one-root structure;
- repeated `ruff`, full pytest, targeted training tests, frontend syntax, Alembic head, checksum, secret/artifact, and advisory-only scans against the re-extracted tree;
- confirmed absence of `.env`, credentials, `.venv`, caches, `*.pyc`, `*.egg-info`, build/dist, dumps, real model artifacts, and obsolete checksum files.

The final ZIP SHA-256 is reported externally because embedding the archive hash inside itself would change the hash. `SHA256SUMS` covers the final release tree contents.
