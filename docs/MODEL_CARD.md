# Model card

## Purpose

The runtime model estimates direction-conditional TP/SL/TIMEOUT market outcomes for hourly crypto perpetual opportunities. It is used by policy and sizing layers to produce advisory recommendations, not autonomous exchange orders.

## Non-goals

- The model card is not proof of live profitability.
- Backtests and reports are evidence inputs, not guarantees of live edge.
- `NO_TRADE` is a policy decision, not a market outcome class.

## Required evidence

- Purged temporal split and final holdout validation.
- Probability calibration and class mapping checks.
- Candidate/incumbent comparison against compatible holdout evidence.
- Immutable artifact hash, metadata, schema, horizon, and class metadata.
- Drift reference tied to the active artifact.

## 1.52.13 note

This patch does not change model training, inference, features, classes, artifacts, or activation policy. It changes only execution-plan risk diagnostics after the model signal exists.
