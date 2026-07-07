# Iteration report — 2026-07-07 — terminal inference coverage accounting

## 1. Input

- Archive: `cost_aware_momentum-1.48.0-policy-sparse-pool-jackknife.zip`
- SHA-256: `d30af01cd6372f7bd4174475f858a2d6ca40c3f0967b42992fd57cc22286b9d5`
- Source version: `1.48.0`
- Source inventory: 98 production/script Python files, 115 test Python files, 25 documentation files and 17 migrations.
- Alembic head: `0017_model_artifact_blobs`.

## 2. Goal and acceptance criteria

After this iteration, a successful hourly inference must be considered complete when every selected symbol has one terminal outcome, even if only a few symbols publish recommendations. Production drift must separately report processing coverage and recommendation density.

Acceptance criteria:

1. A 141-symbol job with 141 terminal outcomes and one recommendation is not retried.
2. A job with fewer terminal outcomes than selected symbols remains retryable.
3. Drift coverage equals processed terminal outcomes divided by expected symbol opportunities.
4. Actionability density equals published/existing signals divided by expected symbol opportunities.
5. Sparse recommendations do not create false low-coverage or 100%-actionable evidence.
6. Real actionability-density drift remains critical.
7. Drift reference binds actionability to the final published-policy-trade cohort.
8. Existing fail-closed handling of malformed job evidence is preserved.

## 3. Sources and data flow

Reviewed `README.md`, `CHANGELOG.md`, `PATCH_1.46.0.md` through `PATCH_1.48.0.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md`, `app/services/signals.py`, `app/workers/runner.py`, `app/services/drift_monitor.py`, `app/ml/drift.py`, `app/ml/lifecycle.py` and related tests.

Affected flow:

`selected universe → publish_hourly_signals terminal symbol_outcomes → JobRun.details → retry decision → production drift coverage/actionability → quarantine guard`.

## 4. Baseline

- Python: 3.13.5.
- `python -m pip check`: failed only because shared environment `moviepy 2.2.1` requires `pillow<12`, while Pillow 12.2.0 is installed. The project does not depend on moviepy.
- compileall: passed.
- Ruff: passed.
- pytest: `820 passed, 8 skipped`.
- Node syntax: passed.
- PostgreSQL integration: not run because no isolated test database was configured.

## 5. Confirmed defects

### HIGH — recommendation count was used as inference processing coverage

`publish_hourly_signals()` records one terminal outcome per selected symbol and validates that the count equals `symbols_total`. `should_retry_incomplete_inference()` ignored this evidence and counted only published/existing signals. Correct no-trade or safety skips therefore caused up to five redundant retries.

Impact: unnecessary repeated inference, repeated data reads and operator impression that the process is stuck because recommendations are sparse.

### HIGH — drift coverage conflated successful no-trade processing with missing processing

`build_production_drift_report()` accumulated `published + existing_current_hour` as coverage. A fully processed 100-symbol job with one signal appeared to have 1% coverage and was blocked.

Impact: false `insufficient_inference_coverage`, degraded heartbeat and invalid operational diagnostics.

### HIGH — actionability density was conditioned on already-published signals

The monitor calculated booleans only for `MarketSignal` rows. Since these rows are already published recommendations, observed actionability approached 100%, while the reference rate was calculated over all final-holdout opportunities.

Impact: false `actionability_density_drift` and possible quarantine of a correctly sparse model.

### MEDIUM — reference density used the wrong post-selection stage

The reference used pre-overlap actionable candidates. Production telemetry represents final policy trades after overlap filtering. The rate is now `policy_trades / policy_candidates` and carries an immutable cohort schema.

## 6. Change set

Production:

- `app/workers/runner.py`
- `app/services/drift_monitor.py`
- `app/ml/drift.py`
- `app/ml/lifecycle.py`
- `app/__init__.py`
- `pyproject.toml`

Tests:

- `tests/unit/test_inference_terminal_coverage_accounting_2026_07_07.py`

Documentation/release:

- `README.md`
- `CHANGELOG.md`
- `PATCH_1.49.0.md`
- `docs/QA_REPORT.md`
- `docs/SPEC_COMPLIANCE.md`
- `docs/TRACEABILITY.md`
- this report
- `SHA256SUMS`

No migration or environment variable was added.

## 7. Red → green

Command:

```bash
python -m pytest -q tests/unit/test_inference_terminal_coverage_accounting_2026_07_07.py
```

Untouched 1.48.0: `7 failed, 1 passed`.

The failures demonstrated missing terminal-count retry semantics, absent processed/actionable opportunity accounting, false service-level low coverage and missing actionability cohort binding.

After the fix: `8 passed`.

Focused compatibility:

```bash
python -m pytest -q   tests/unit/test_inference_terminal_coverage_accounting_2026_07_07.py   tests/unit/test_inference_retry.py   tests/unit/test_production_drift_monitoring_2026_07_05.py   tests/unit/test_critical_drift_evidence_precedence_2026_07_06.py
```

Result: `22 passed`.

## 8. Compatibility

- No database schema change.
- No API endpoint change.
- Drift report schema is v4.
- Drift reference schema is v4 and includes `published-policy-trades-per-symbol-opportunity-v1`.
- Old artifact references are intentionally rejected fail-closed; a new candidate is required.
- Older JobRun details without `symbol_outcome_count` remain retry-compatible in the worker, but the production drift monitor treats missing terminal coverage evidence as invalid and blocks rather than guessing.

## 9. Post-check

- compileall: passed.
- Ruff: passed.
- pytest: `828 passed, 8 skipped`.
- Node syntax: passed.
- Alembic: one head, `0017_model_artifact_blobs`.
- No Bybit order-create/update/cancel methods were introduced.
- Advisory-only and PostgreSQL-only boundaries remain intact.

## 10. Not verified

- PostgreSQL integration tests.
- A real 100+ symbol inference job on the operator database.
- Live drift quarantine after accumulation of a complete v4 window.
- All-opportunity feature/probability drift telemetry.
- Forward profitability.

## 11. Residual risks

Feature/probability PSI still uses stored signal rows. A future work package should persist a bounded, immutable inference-opportunity telemetry record for every evaluated symbol, including no-trade outcomes, so distribution drift can use the same denominator as coverage and actionability.

## 12. Rollback

Stop worker/API/trainer, restore version 1.48.0 and its compatible model artifact. Database downgrade is unnecessary. A 1.49.0 artifact uses drift reference v4 and must not be relabelled for 1.48.0.

## 13. Recommended next work package

Add an immutable, bounded all-opportunity inference telemetry ledger and align feature/probability PSI with the same symbol-opportunity population. Do not infer no-trade feature distributions from published signals.
