# Changelog

## 1.26.4 — 2026-07-05

### Fixed

- Policy evaluation now builds economic mean and uncertainty evidence over every observed hourly decision cohort, not only cohorts in which a trade survived the policy and overlap filters.
- An observed `NO TRADE` cohort contributes a known zero strategy return and zero expected policy contribution; missing market hours are not invented.
- Quality-gate evidence exposes and validates `policy_trade_cohorts` and `policy_no_trade_cohorts`; incumbent comparison rejects missing or inconsistent opportunity accounting.
- Policy metric schemas were raised to opportunity-path v17 and uncertainty v3, so legacy conditional-on-trade evidence cannot be reused for normal promotion.

### Compatibility

- No database migration, public HTTP API change or `.env` addition.
- Already active artifacts remain runnable. Inactive candidates evaluated under the previous policy schemas must be retrained and their governed experiment evidence regenerated before normal activation.

### Verification

- Clean isolated baseline: 613 passed, 4 skipped.
- Post-change suite: 615 passed, 4 skipped, 61 warnings.

## 1.26.3 — 2026-07-05

### Fixed

- Experiment promotion now rejects a `READY` selected trial when its deployment-relevant policy differs from the candidate/production contract: entry spread, research leverage/reserve, fees, slippage, stop-gap reserve, funding/timeout overrides, EV/RR thresholds, policy source or portfolio accounting.
- Candidate training persists an immutable `model-promotion-policy-binding-v1` contract; deferred trainer promotion, manual training activation and registry activation all require the same contract.
- Activation revalidates the persisted policy binding against current deployment settings, so changing policy after backtesting invalidates stale evidence instead of silently deploying a different strategy.

### Compatibility

- Promotion gate schema is now `model-promotion-experiment-governance-v2`.
- No database migration, public HTTP API change or `.env` addition.
- Already active artifacts remain runnable. Inactive candidates created before 1.26.3 lack policy binding and require retraining for normal activation; explicit reasoned emergency rollback remains available.

### Verification

- Clean isolated baseline: 609 passed, 4 skipped.
- Post-change suite: 613 passed, 4 skipped.

## 1.26.2 — 2026-07-05

### Fixed

- Background trainer now reconciles already registered inactive candidates after preregistered experiment evidence becomes `READY`; previously evidence was checked only during the same call that created a fresh artifact.
- Model activation logic used by the CLI and trainer now shares one production service with the same quality, experiment-binding, artifact-integrity, concurrency, audit and outbox checks.
- A successful deferred activation ends the scheduling iteration instead of immediately starting another training run.

### Configuration

- Added `AUTO_TRAIN_EXPERIMENT_FAMILY=` to `.env.example`. Empty or non-READY evidence remains fail-closed and leaves the candidate inactive.
- No database migration, risk-threshold change or artifact-schema change.

### Verification

- Clean isolated baseline: 606 passed, 4 skipped.
- Post-change suite: 609 passed, 4 skipped.
