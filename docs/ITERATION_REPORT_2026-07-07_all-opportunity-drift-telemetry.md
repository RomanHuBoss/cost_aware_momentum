# Iteration report — all-opportunity production drift telemetry

## 1. Input

- Archive: `cost_aware_momentum-main.zip`.
- SHA-256: `acc2869c3265fc3ca4db7b3a94dd9b3555197dee8d6167e1bb2717df9d16fd8e`.
- Source version: `1.49.1`.
- Source Alembic head: `0017_model_artifact_blobs`.
- Python requirement: `>=3.12`; QA interpreter: `3.13.5`.
- Initial inventory: 301 regular release files, including 122 production/support files, 116 test files and 53 documentation files; 17 Alembic revisions.
- No `.env`, credentials, virtual environment, model artifacts, database dumps or release build directories were present in the input archive.

## 2. Goal and acceptance criteria

After this iteration, production feature/probability drift must use every successful active-artifact evaluation that has a complete point-in-time feature vector, before downstream trading-policy filters, while preserving published mature signals as the realized calibration cohort.

Acceptance criteria:

1. Immutable PostgreSQL row for the first successful `(model_version, symbol, event_time)` evaluation.
2. Row contains model, calibration and feature-schema identity plus exact features and both directional probabilities.
3. Persistence occurs before spread, funding, EV/RR and publication filters.
4. Retry/concurrency is idempotent and cannot mutate the first observation.
5. Drift PSI reads the new ledger; calibration still reads mature published signals/outcomes.
6. Invalid ledger evidence blocks fail-closed.
7. One Alembic head, full unit suite and static checks remain green.

## 3. Sources and data flow

Read: `README.md`, `CHANGELOG.md`, `pyproject.toml`, `.env.example`, the latest patch/iteration reports, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, model lifecycle/drift/signal code, ORM/migrations and relevant tests. The separate architecture/security/operator/model-card documents named by the iterative prompt are not present in this archive. No separate DOCX specification was attached in this iteration.

Changed flow:

`confirmed decision candle + point-in-time context` → `runtime.predict_scenarios` → **immutable inference observation** → `spread/funding/economics/policy filters` → optional `MarketSignal` → mature `SignalOutcome`.

Drift flow:

- features/probabilities: `ModelInferenceObservation`;
- processing/actionability denominators: hourly inference `JobRun` terminal accounting;
- calibration/outcomes: mature published `MarketSignal` + `SignalOutcome`.

## 4. Baseline before changes

An initial global-environment attempt was rejected as an authoritative baseline because `psycopg` and `ruff` were absent and an unrelated global `moviepy/Pillow` conflict affected `pip check`. A clean external venv was then created and project dev dependencies installed.

| Command | Result |
|---|---|
| `python --version` | PASSED — Python 3.13.5 |
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 829 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| `python manage.py doctor` | NOT RUN to completion — command requires a project-local environment created by `manage.py setup`; QA used an external isolated venv |
| `python manage.py test --require-integration` | NOT RUN — no isolated PostgreSQL `TEST_DATABASE_URL`; production DB was not used |

## 5. Confirmed gap

### HIGH — policy-conditioned production drift sample

- Location before fix: `app/services/drift_monitor.py::build_production_drift_report`.
- Actual behavior: feature and probability rows were extracted from `MarketSignal.feature_snapshot`.
- Selection path: a `MarketSignal` is created only after exact-candle/context validation and after spread, funding, probability/economics, EV/RR and publication decisions.
- Reproduction: the new regression constructs six severely shifted pre-policy observations but only one stable published signal. Untouched 1.49.1 cannot even represent the observations because `ModelInferenceObservation` is absent.
- Expected: PSI sees all six artifact evaluations and detects feature/probability drift.
- Impact: rare publication can suppress production model-safety evidence. This can contribute to delayed drift detection but does not prove the source of any particular losing trade.
- Why old tests missed it: fixtures started at published signals and therefore could not assert coverage of rejected model-evaluable opportunities.

## 6. Change set

Production:

- `app/db/models.py` — immutable observation ORM contract and PostgreSQL constraints.
- `app/services/signals.py` — pre-policy artifact telemetry, idempotent advisory-lock persistence and diagnostics.
- `app/services/drift_monitor.py` — all-opportunity feature/probability rows; mature published calibration retained.
- `migrations/versions/0018_inference_observations.py` — table/index/trigger and downgrade.

Tests:

- New `tests/unit/test_all_opportunity_drift_telemetry_2026_07_07.py`.
- Updated drift service fixtures for the new observation query and explicit terminal/actionability accounting.
- Updated migration-head contract.

Documentation/release:

- Version `1.50.0`, changelog, README, patch note, QA, compliance, traceability, this report and regenerated `SHA256SUMS`.

## 7. Red → green evidence

Red against untouched 1.49.1:

```text
ImportError: cannot import name 'ModelInferenceObservation' from 'app.db.models'
```

Green checks cover:

- ORM table/unique/immutability migration contract;
- artifact/calibration/schema-bound idempotent persistence;
- six shifted pre-policy observations versus one stable published signal, with PSI driven by the six observations;
- migration revision length and single-head contract.

The final suite adds three tests relative to baseline: 829 → 832 passed.

## 8. Migration/API/config compatibility

- New head: `0018_inference_observations`.
- Required action: stop processes, run `python manage.py migrate`, restart API/worker/trainer.
- `.env`: no changes.
- API/UI: no contract changes.
- Model artifact: no schema/retraining requirement; existing active artifact remains compatible.
- Ledger history is prospective. Pre-upgrade rejected opportunities cannot be reconstructed.
- Downgrade removes telemetry rows and is therefore data-destructive for this new ledger only.

## 9. Post-check

| Command | Result |
|---|---|
| `python -m pip check` | PASSED |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED — 832 passed, 8 skipped, 62 warnings |
| `node --check web/js/app.js` | PASSED |
| Alembic revision/head contract | PASSED — one head `0018_inference_observations`, IDs ≤32 characters |
| Alembic PostgreSQL offline SQL | PASSED — base → head, 1,448 lines |
| Live PostgreSQL integration/migration | NOT RUN — isolated server unavailable |

## 10. Unverified

- Actual upgrade/downgrade and immutable trigger behavior on a live isolated PostgreSQL instance.
- Long-running worker throughput/storage growth under a large dynamic universe.
- Prospective drift behavior after minimum-observation warm-up.
- Economic profitability or causal explanation of historical losses.

## 11. Residual risks and limitations

- Historical pre-1.50 no-trade feature/probability observations do not exist.
- Monitor remains univariate PSI plus calibration/actionability checks; it does not implement multivariate drift, adaptive control limits or automated rollback.
- A prediction that raises before producing a complete directional probability vector is represented by terminal inference diagnostics, not by this probability ledger.
- Warnings from NumPy/joblib deprecations remain unchanged.

## 12. Rollback

1. Stop API, worker and trainer.
2. Export telemetry if it must be retained.
3. Run Alembic downgrade to `0017_model_artifact_blobs`.
4. Restore release 1.49.1 code.
5. Restart processes.

Rollback removes `model.model_inference_observations`; it does not change signals, outcomes, artifacts or risk state.

## 13. Recommended next work package

Add an isolated PostgreSQL migration/integration run for `0018`, including concurrent duplicate insertion and trigger-enforced UPDATE/DELETE rejection, then observe at least one full drift window before changing any gate threshold.
