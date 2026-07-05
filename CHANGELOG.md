# Changelog

## 1.26.6 — 2026-07-05

### Fixed

- Experiment/backtest capital paths now recognize cumulative hourly mark-price MTM instead of posting the entire trade P&L only at the modeled exit timestamp.
- Intratrade drawdowns that recover before exit now affect portfolio drawdown, Sharpe, HAC/DSR, PBO and moving-block evidence.
- Entry fee and conservative slippage are recognized at decision time; historical funding follows the cumulative settlement path; terminal barrier/liquidation return and exit fee reconcile exactly at effective exit.
- Research metadata now carries a validated, complete hourly MTM path from decision through effective exit. Missing, malformed, non-hourly or non-reconciling paths fail closed before experiment evidence is emitted.
- Experiment return-path schema was raised to `observed-opportunity-covered-hourly-mark-to-market-capital-return-path-v3`; predecessor exit-realized v2 evidence is rejected.

### Compatibility

- No database migration, public HTTP API change, model feature/artifact schema change, risk-threshold change or `.env` addition.
- Active artifacts remain runnable. Existing experiment families containing successful v2 trials must rerun preregistered backtests before normal promotion.
- Backtest configuration binding now identifies `horizon_sleeves_hourly_mark_to_market_single_active_symbol_v3`.

### Verification

- Clean isolated baseline: 618 passed, 4 skipped.
- Post-change suite: 622 passed, 4 skipped, 62 warnings.

## 1.26.5 — 2026-07-05

### Fixed

- Backtest experiment return paths now use the union of actually observed decision-to-horizon windows instead of a continuous calendar range between the first decision and final exit.
- Missing market/data hours are no longer inserted as zero returns, so they cannot inflate period counts or distort Sharpe, DSR, PBO and dependence evidence.
- Genuine observed `NO TRADE` and holding hours remain explicit zero-return periods inside covered windows.
- Experiment evidence now records observed-opportunity, covered-period and omitted-gap counts and validates their arithmetic before governance analysis.
- Legacy `hourly-realized-capital-return-path-v1` evidence is rejected; normal promotion returns a diagnostic fail-closed gate instead of propagating an unhandled validation error.

### Compatibility

- No database migration, public HTTP API change, risk-threshold change or `.env` addition.
- Existing experiment families containing legacy successful trials must be rerun under the v2 return-path schema before normal model promotion. Active models are not deactivated.

### Verification

- Clean isolated baseline: 615 passed, 4 skipped.
- Post-change suite: 618 passed, 4 skipped, 61 warnings.

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
