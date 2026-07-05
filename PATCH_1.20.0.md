# Patch 1.20.0 — formal experiment-family preregistration

## Problem

Release 1.19.0 disclosed trial attempts and applied PBO, Deflated Sharpe and dependence-aware inference, but an experiment family was only a string supplied at backtest time. A researcher could define or alter the hypothesis, search space, primary metric, thresholds, stopping rule or exclusions after observing one or more results. The ledger was prospective at trial level but not preregistered at family level.

## Solution

Release 1.20.0 adds an immutable PostgreSQL preregistration that must exist before the first `STARTED` event. The registration contains:

- substantive hypothesis;
- exact final-test dataset fingerprint and horizon as fixed parameters;
- complete partition of configuration keys into fixed parameters and enumerated search values;
- primary metric `nonannualized_sharpe`, direction `maximize`;
- PBO, DSR, minimum-period and dependence policy;
- maximum unique configurations and optional UTC deadline;
- objective pre-result exclusion criteria.

The record is protected by a canonical SHA-256 and a PostgreSQL trigger that rejects `UPDATE` and `DELETE`. `append_experiment_event()` locks the family registration, validates the configuration and stopping rule, and embeds the registration hash in `STARTED` evidence. Reports use the registered governance values and block mismatching command-line overrides.

## Workflow

1. Generate an unevaluated template after the exact cohort/configuration is known:

```bash
python manage.py backtest -- \
  --model models/candidate.joblib \
  --experiment-family momentum-policy-study-01 \
  --prepare-preregistration research/momentum-policy-study-01.json \
  --search-parameter minimum_net_rr \
  --search-parameter minimum_net_ev_r
```

The command exits before experiment `STARTED` and before model evaluation.

2. Replace all placeholders, enumerate every permitted search value, and set the stopping rule.
3. Validate without PostgreSQL:

```bash
python manage.py experiment-preregister -- \
  --spec research/momentum-policy-study-01.json \
  --validate-only
```

4. Apply migration `0013_experiment_preregistration` and register once:

```bash
python manage.py migrate
python manage.py experiment-preregister -- \
  --spec research/momentum-policy-study-01.json
```

5. Run every planned backtest with the exact registered family.

## Compatibility

- Database migration required: `0013_experiment_preregistration`.
- No new environment variables.
- No model retraining required.
- Market-model artifact schema is unchanged.
- Pre-1.20 experiment families remain visible but `experiment-report` returns `BLOCKED_UNREGISTERED_FAMILY`; they are not retrospectively presented as preregistered.
- Existing experiment events are not rewritten.

## Validation

- Baseline: 559 passed, 4 skipped.
- Post-change: 568 passed, 4 skipped.
- Focused preregistration module: 9 passed.
- Ruff, compileall, frontend syntax and Alembic-head checks passed.
- PostgreSQL integration migration was not executed because no isolated `TEST_DATABASE_URL` was available.

## Limitations

- Registration time is the application/database event time, not an external trusted timestamp authority.
- Search space is enumerated per parameter and permits the Cartesian product; conditional parameter spaces are not represented.
- Exclusion criteria are immutable disclosure metadata; automated classification of runtime failures into an exclusion code is not implemented.
- Formal preregistration is research governance only and does not automatically activate or reject a market model.
