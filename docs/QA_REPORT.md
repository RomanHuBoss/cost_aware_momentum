# QA Report

Release: **1.49.0**
Date: **2026-07-07**
Scope: **terminal inference coverage and actionability-density accounting**

## Environment and input

- Python: 3.13.5; project requirement: Python >=3.12.
- Input archive: `cost_aware_momentum-1.48.0-policy-sparse-pool-jackknife.zip`.
- Input SHA-256: `d30af01cd6372f7bd4174475f858a2d6ca40c3f0967b42992fd57cc22286b9d5`.
- Source version: 1.48.0.
- Source inventory: 98 production/script Python files, 115 test Python files, 25 documentation files and 17 migrations.
- Alembic head before and after: `0017_model_artifact_blobs`.
- Separate PostgreSQL integration database: not configured.

## Baseline before production changes

| Check | Result |
|---|---|
| `python --version` | PASSED: Python 3.13.5 |
| `python -m pip check` | FAILED: unrelated shared-environment conflict, `moviepy 2.2.1` requires `pillow<12`, installed Pillow is 12.2.0 |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 820 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |

`python manage.py doctor` and `python manage.py test --require-integration` were not run because no operator configuration or isolated PostgreSQL test URL was available. No production database was accessed.

## Confirmed defects and red evidence

The eight-test regression was run against untouched 1.48.0: **7 failed, 1 passed**.

The failures proved that:

- a fully processed sparse inference was retried because only recommendation count was treated as coverage;
- drift had no separate processed/actionable opportunity counts;
- low recommendation density was misreported as low processing coverage;
- actionability was conditioned on already-published signals and could appear as 100%;
- drift references did not bind the actionability denominator to final published policy trades.

The control test confirmed that genuinely incomplete terminal coverage remained retryable.

## Post-change verification

| Check | Result |
|---|---|
| New regression | PASSED: 8 passed |
| Focused inference/drift compatibility | PASSED: 22 passed |
| `python -m compileall -q app scripts tests manage.py` | PASSED |
| `python -m ruff check .` | PASSED |
| `python -m pytest -q` | PASSED: 828 passed, 8 skipped |
| `node --check web/js/app.js` | PASSED |
| Alembic heads | PASSED: one head, `0017_model_artifact_blobs` |

The eight skipped tests require an isolated PostgreSQL database.

## Release boundary

- No migration and no `.env` change.
- Production drift reference schema increased to `final-holdout-feature-probability-selected-calibration-reference-v4`.
- Production drift report schema increased to `production-drift-report-v4`.
- Actionability cohort is bound to `published-policy-trades-per-symbol-opportunity-v1`.
- Inference completion uses exact `symbol_outcome_count`; recommendation count is no longer processing coverage.
- Pre-1.49 artifacts require retraining because their drift reference uses v3 semantics.
- Existing model-quality, calibration, EV/RR, holdout, walk-forward, spread, leverage and risk thresholds were not weakened.
- Advisory-only, PostgreSQL-only and read-only Bybit boundaries remain unchanged.

## Residual limitations

- Full training/promotion/runtime loading was not executed against the operator PostgreSQL/Bybit environment.
- Feature and probability PSI still use stored signal rows rather than an immutable ledger of every evaluated no-trade opportunity.
- Symbol/regime-conditional production drift is not implemented.
- This change corrects accounting and retry semantics; it does not prove forward profitability.
