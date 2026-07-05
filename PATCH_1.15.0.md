# Patch 1.15.0 — prospective operator-selection experiment ledger

## Problem

Counterfactual plan outcomes existed for accepted and unaccepted plans, but the project did not freeze whether a specific plan version was eligible at the moment it was created. Operational reporting counted operator actions and manual trades without comparing the selected subset with every eligible recommendation. As a result, accepted-only performance could be materially distorted by operator selection and by later mutations of plan status.

## Solution

- Added immutable `advisory.selection_experiment_ledger`, one row per plan version.
- The row is created in the execution-plan transaction before any operator decision.
- Stored features use a fixed numeric ex-ante schema and exclude action, outcome, counterfactual R and realized P&L.
- A canonical SHA-256 covers identifiers, timestamp, eligibility, schemas, features and release version.
- Added a chronological expanding logistic propensity model with only out-of-sample predictions.
- Added stabilized inverse-probability-of-selection weighting for the accepted subset.
- The direct mean of all eligible valued counterfactual outcomes remains the primary benchmark because outcomes are available for selected and unselected plans.
- Corrected output is blocked on insufficient samples, class collapse, missing temporal OOS scores, poor overlap, low effective sample size or ledger-integrity failure.
- Added a dedicated selection report and integrated the same diagnostics into the daily report.

## Database

Apply migration:

```bash
python manage.py migrate
```

Expected head:

```text
0011_selection_experiment
```

No legacy opportunities are backfilled. Evidence starts prospectively from plan versions created after the upgrade.

## Configuration

No new `.env` variables are required. ML retraining is not required.

Commands:

```bash
python manage.py selection-report -- --days 90
python manage.py report -- --hours 24 --selection-days 90
```

## Verification

- Baseline: 514 passed, 4 skipped.
- Post-change: 522 passed, 4 skipped.
- New selection module: 7 tests.
- Additional execution transaction regression: 1 test.
- Ruff, compileall, frontend syntax and Alembic single-head checks pass.
- PostgreSQL integration remains skipped without an isolated `TEST_DATABASE_URL`.

## Limitations

- The unit is a created plan version, not a proven UI impression.
- Automatic recalculations can create correlated opportunities for the same signal/profile.
- Counterfactual outcomes are modelled advisory outcomes, not exchange-confirmed fills.
- IPSW is descriptive selection diagnostics, not a causal estimate of operator skill.
- Latent operator state, cluster-robust inference and pre-1.15 opportunities are unavailable.
