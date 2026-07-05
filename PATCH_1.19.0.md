# Patch 1.19.0 — dependence-aware research inference

## Problem

Release 1.18.0 disclosed experiment variants and calculated PBO/DSR, but DSR still used the nominal count of serially dependent hourly returns. Operator-selection diagnostics treated plan versions as independent for uncertainty and chronological propensity blocks could cut through versions of one signal. Both paths could materially overstate precision.

## Solution

- Added Bartlett/Newey–West long-run variance and effective observation count for return means.
- Added deterministic moving-block bootstrap intervals for selected experiment mean return and non-annualized Sharpe.
- Enforced an experiment block length no shorter than the declared trading horizon and a minimum number of independent blocks.
- Adjusted DSR inference by HAC effective observations and required positive lower HAC/bootstrap bounds for a `READY` family report.
- Grouped all plan versions of one signal in chronological propensity splitting; training excludes clusters overlapping the OOS block start.
- Added signal-cluster moving-block intervals for eligible, selected, IPSW and selected-subset-bias estimates.
- Added fail-closed settings and regression tests. No model, risk, execution or activation behavior is changed.

## Database and model compatibility

- No Alembic migration. Expected head remains `0012_experiment_selection`.
- No market-model retraining or artifact schema change.
- Existing prospective experiment and selection ledgers remain valid.

## Configuration

Review:

```env
RESEARCH_BOOTSTRAP_REPLICATES=1000
RESEARCH_CONFIDENCE_LEVEL=0.95
EXPERIMENT_DEPENDENCE_BLOCK_PERIODS=8
EXPERIMENT_MIN_INDEPENDENT_BLOCKS=6
SELECTION_DEPENDENCE_BLOCK_CLUSTERS=5
SELECTION_MIN_INDEPENDENT_CLUSTERS=30
```

The experiment effective block length is `max(EXPERIMENT_DEPENDENCE_BLOCK_PERIODS, declared horizon)`. Bootstrap results are deterministic for the same evidence and release seed. These settings classify research reports only.

## Verification

- Baseline: `550 passed, 4 skipped`.
- Post-change: `559 passed, 4 skipped`.
- New regression module: nine tests; source version failed collection because `app.research.dependence` did not exist.
- Compileall, Ruff, dependency check, frontend syntax and Alembic single-head checks passed in the isolated project environment.
- PostgreSQL integration tests were not executed because no isolated `TEST_DATABASE_URL` was supplied.

## Limitations

- Block lengths are governance assumptions and require domain review.
- Percentile intervals are not studentized or bias-corrected.
- Operator bootstrap conditions on fitted chronological OOS propensity scores rather than refitting the model in every replicate.
- UI exposure, latent operator state and pre-1.15 opportunities remain unavailable.
- Results do not establish causal operator skill or future profitability.
