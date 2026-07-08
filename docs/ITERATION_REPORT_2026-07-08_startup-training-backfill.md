# Iteration report — 2026-07-08 — startup training backfill

## 1. Input archive and baseline identity

- Input archive: `cost_aware_momentum-main(1).zip`.
- Input archive SHA-256: `5e51ea6dc48ded4cf7f4695f2a17a04015ebeccd72a02acfadb31ce84b9c2a51`.
- Input version: `1.52.5`.
- Output version: `1.52.6`.
- Python: `3.13.5`; project requirement: `>=3.12`.
- Alembic head: `0018_inference_observations`.
- Input tree summary after unpack: one root directory; 99 production-ish files, 123 test files, 27 documentation/top-level markdown files.
- Input release artifacts: no `.env`, virtualenv, build/dist, `*.egg-info`, real model artifacts or dumps detected. Runtime caches were created only by local checks and are excluded from the output ZIP.

## 2. Goal and acceptance criteria

After this iteration, a clean startup market-data sync must be capable of loading enough hourly candles for the existing default training quality-gate preflight without lowering ML/econometric gates.

Acceptance criteria:

1. Default `INITIAL_BACKFILL_BARS` is greater than or equal to the current default minimum hourly history required by `minimum_hourly_history_timestamps_for_quality_gate()`.
2. `sync_candles()` can request and store more than one Bybit kline page when the caller asks for more than 1000 candles.
3. Pagination is idempotent by candle open time and does not duplicate rows across pages.
4. Existing fail-closed partial/failed request behavior is preserved.
5. Risk math, model thresholds, temporal split, holdout, policy, promotion and activation gates are not weakened.
6. No database migration, API contract change or model artifact schema change is introduced.
7. New tests demonstrate red on the unchanged 1.52.5 production behavior and green after the fix.
8. Full unit test suite and static checks pass in the available sandbox after dependency repair.

## 3. Sources read and affected data flow

Sources read:

- `README.md`, `CHANGELOG.md`, `PATCH_1.52.3.md`, `PATCH_1.52.4.md`, `PATCH_1.52.5.md`.
- `pyproject.toml`, `.env.example`.
- `docs/ARCHITECTURE.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `docs/MODEL_CARD.md`, `docs/CONFIGURATION.md`, `docs/SECURITY.md`, `docs/INCIDENT_RUNBOOK.md`, `docs/OPERATOR_MANUAL.md`.
- Relevant production modules: `app/config.py`, `app/services/market_data.py`, `app/bybit/client.py`, `app/ml/training.py`, `app/ml/lifecycle.py`, `app/workers/trainer.py`.
- Relevant tests: dynamic bootstrap, walk-forward validation, candle retry, candle availability integrity and trainer readiness tests.

Affected data flow:

```text
Settings.initial_backfill_bars
  -> market-data worker startup sync
  -> app.services.market_data.sync_candles()
  -> Bybit read-only kline pages
  -> candle normalization/upsert
  -> training data profile / quality-gate preflight
  -> trainer waits or attempts candidate fit
```

## 4. Baseline before production changes

| Command | Status | Result |
|---|---|---|
| `python --version` | PASSED | `Python 3.13.5` |
| `python -m pip check` | FAILED / environment limitation | `moviepy 2.2.1` requires `pillow<12.0`, installed `pillow 12.2.0` |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | UNAVAILABLE | `No module named ruff` before dependency repair |
| `python -m pytest -q` | FAILED / environment limitation | collection interrupted with `61 errors`; primary cause `ModuleNotFoundError: No module named 'psycopg'` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python manage.py doctor` | NOT RUN in baseline | delayed until post checks; no project-local `.venv` |
| `python manage.py test --require-integration` | NOT RUN in baseline | safe PostgreSQL test database not configured |

Baseline was not green because the shared sandbox was missing project dependencies and had an unrelated `moviepy`/`pillow` conflict.

## 5. Confirmed defects/gaps

### CONFIRMED DEFECT — startup history default below model-readiness minimum

- Severity: high operational/model-readiness risk.
- Files: `app/config.py`, `.env.example`.
- Evidence: default `Settings.initial_backfill_bars` was `1000`, while `minimum_hourly_history_timestamps_for_quality_gate()` returns `1206` for default horizon, holdout rows and holdout span.
- Expected behavior: the default startup backfill should be capable of reaching the existing training precondition when historical exchange data exists.
- Actual behavior: a clean startup could complete initial sync below the mathematical training minimum and keep the trainer waiting for progressive history accumulation.
- Why existing tests missed it: no regression asserted consistency between default backfill depth and the training preflight minimum.

### CONFIRMED DEFECT — raising the default alone would still not fetch enough candles

- Severity: high operational/model-readiness risk.
- File/function: `app/services/market_data.py::sync_candles()`.
- Evidence: `sync_candles()` previously passed caller `limit` to `client.get_kline()` once. `app/bybit/client.py::get_kline()` clamps a single request to at most 1000 rows, so a caller asking for 1206/1500 rows could still receive only one page.
- Expected behavior: the sync path should paginate read-only kline requests when the desired depth exceeds one exchange page.
- Actual behavior: no pagination existed in this path.
- Why existing tests missed it: candle retry/availability tests covered partial failures and confirmed timestamps, not multi-page startup depth.

## 6. Plan and actual diff

Plan:

- Add a regression test binding the default startup depth to the current training preflight minimum.
- Add a regression test proving multi-page kline sync for a 1206-row request.
- Increase the default startup backfill to a conservative 1500 bars.
- Add pagination inside `sync_candles()` while preserving read-only behavior and idempotent upsert.
- Update version, docs, QA and patch notes.

Production files changed:

- `app/config.py`
- `app/services/market_data.py`
- `app/__init__.py`

Test files changed:

- `tests/unit/test_initial_training_backfill_readiness_2026_07_08.py`

Configuration files changed:

- `.env.example`
- `pyproject.toml`

Documentation files changed:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.52.6.md`
- `docs/CONFIGURATION.md`
- `docs/OPERATOR_MANUAL.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- `docs/ITERATION_REPORT_2026-07-08_startup-training-backfill.md`

Migrations changed: none.

## 7. Red → green evidence

New tests:

```text
tests/unit/test_initial_training_backfill_readiness_2026_07_08.py::test_default_initial_backfill_covers_training_quality_gate_precondition
tests/unit/test_initial_training_backfill_readiness_2026_07_08.py::test_sync_candles_paginates_initial_backfill_beyond_bybit_page_limit
```

Red command after adding tests on unchanged 1.52.5 production code:

```bash
python -m pytest -q tests/unit/test_initial_training_backfill_readiness_2026_07_08.py
```

Red result: `2 failed`.

Substantial failure lines:

```text
E       AssertionError: assert 1000 >= 1206
E       assert 1000 == 1206
```

Green command after fix:

```bash
python -m pytest -q tests/unit/test_initial_training_backfill_readiness_2026_07_08.py
```

Green result: `2 passed`.

Targeted regression suite:

```bash
python -m pytest -q \
  tests/unit/test_initial_training_backfill_readiness_2026_07_08.py \
  tests/unit/test_historical_dynamic_bootstrap_2026_07_07.py \
  tests/unit/test_walk_forward_validation_2026_07_05.py \
  tests/unit/test_hourly_candle_retry_2026_07_04.py \
  tests/unit/test_candle_availability_integrity_2026_07_03.py
```

Result: `20 passed`.

## 8. Migration, API, config and compatibility

- Alembic migration: not required.
- API contract: unchanged.
- Model artifact schema/classes/horizon contract: unchanged.
- Risk/execution math: unchanged.
- Existing `.env` files with `INITIAL_BACKFILL_BARS=1000` remain accepted, but the recommended value is now `1500`.
- Rollout action: update existing local `.env` if it pins `INITIAL_BACKFILL_BARS=1000`, then restart worker and trainer.

## 9. Post-check

| Command | Status | Result |
|---|---|---|
| `python -m pip check` | FAILED / environment limitation | same external `moviepy`/`pillow` conflict |
| `python -m compileall -q app scripts tests manage.py` | PASSED | exit 0 |
| `python -m ruff check .` | PASSED | `All checks passed!` |
| `python -m pytest -q` | PASSED | `861 passed, 8 skipped in 27.87s` |
| targeted regression suite | PASSED | `20 passed` |
| `node --check web/js/app.js` | PASSED | exit 0 |
| `python -m alembic heads` | PASSED | `0018_inference_observations (head)` |
| `python manage.py release-check --write && python manage.py release-check` | PASSED | `Release integrity PASSED: 285 files checked, 285 manifest entries` |
| `python manage.py doctor` | FAILED / environment limitation | no project-local `.venv`; command reports `python manage.py setup` is required |
| `python manage.py test --require-integration` | FAILED / environment limitation | no project-local `.venv`; safe PostgreSQL `TEST_DATABASE_URL` not configured |

## 10. Not verified

- PostgreSQL integration tests were not run because no separate safe PostgreSQL test database/project-local environment was configured.
- `manage.py doctor` could not complete in this sandbox because the expected project-local virtual environment is absent.
- Live Bybit/network smoke was not run and no credentials were used.
- Economic profitability, forward performance and paper/shadow evidence are not claimed.

## 11. Residual risks and limitations

- A 1500-candle startup request per symbol/price type increases public market-data calls when the universe is large. This is necessary to avoid the 1000-row single-page ceiling but should still be watched for rate-limit pressure.
- Training can still defer if feature/context/label filtering, universe eligibility, missing point-in-time specs, class collapse, holdout quality or policy gates fail. This patch intentionally does not bypass those gates.
- One week of wall-clock operation is not itself enough proof of model quality; it is enough to avoid waiting for roughly 50 days when historical hourly data is already available.

## 12. Rollback procedure

1. Revert version `1.52.6` changes to `app/config.py`, `app/services/market_data.py`, `.env.example`, tests and docs.
2. Set local `.env` `INITIAL_BACKFILL_BARS=1000` only if the operator accepts the old slower readiness behavior.
3. Restart worker and trainer.
4. No database rollback is needed because no migration was added.

## 13. Recommended next work package

Implement a bounded, rate-limit-aware universe bootstrap planner that estimates required market-data pages for the active universe before startup sync, records a per-symbol backfill coverage report, and exposes it in trainer diagnostics. Do not lower quality gates for this; use it to make readiness ETA and missing-history causes explicit.
