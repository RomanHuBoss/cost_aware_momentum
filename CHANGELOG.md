# Changelog

## 1.28.2 — 2026-07-06

### Fixed

- Dynamic model-training symbols are no longer selected from the latest 24-hour ticker turnover and projected backward over the historical lookback.
- The capped training cohort now uses confirmed last-price candle coverage ending at the label cutoff, requires the configured minimum rows per symbol and excludes stale symbols that do not reach the cutoff.
- Background training pins the exact symbol list from its preflight `training_data_profile` through data loading and fit, eliminating a time-of-check/time-of-use universe race.
- An explicit empty cohort remains empty and fails closed; it no longer has the same internal meaning as unrestricted symbol loading.
- Manual training uses the same horizon and minimum-history selection contract as the background trainer.

### Compatibility

- No database migration, public HTTP API change, `.env` addition, model artifact schema change or recommendation-threshold change.
- Existing active artifacts remain valid. Retrain a candidate to obtain evidence under the corrected historical cohort-selection contract.
- Default gates remain unchanged: approximately one day of hourly data still cannot satisfy the configured minimum of 1206 unique timestamps.

### Verification

- Clean isolated baseline: 644 passed, 4 skipped, 62 warnings.
- Red evidence: dynamic selection returned the latest-turnover `HOT_NEW_USDT` instead of the label-eligible mature-history cohort.
- Post-change suite: 645 passed, 4 skipped, 62 warnings.

## 1.28.1 — 2026-07-06

### Fixed

- Production drift status no longer lets incomplete coverage, warm-up or maturity evidence overwrite independently confirmed `CRITICAL` drift.
- Drift report v3 records separate `critical_evidence`, `blocking_evidence` and `warning_evidence` lists and resolves overall safety status deterministically: critical evidence first, then blocked, warning and OK.
- Feature missingness is considered critical only when the configured feature-observation denominator is available; a completely empty warm-up window remains `BLOCKED` rather than becoming a false critical alarm.
- Incomplete/invalid mature-outcome coverage invalidates calibration-only drift evidence, while preserving independent feature, probability and actionability critical evidence.
- Report post-processing for failed inference jobs, invalid coverage accounting and incomplete outcomes now adds blocking evidence without suppressing an already confirmed independent critical condition.

### Compatibility

- No database migration, public HTTP API change, `.env` addition, model artifact change or recommendation-threshold change.
- Persisted drift report schema is raised from `production-drift-report-v2` to `production-drift-report-v3`; the existing quarantine guard still recognizes previously persisted v2 reports with status `CRITICAL`.
- Pure insufficient-observation reports remain non-quarantining to avoid monitor bootstrap deadlock. Any report with valid independent critical evidence now quarantines the exact active model version even when another evidence dimension is blocked.

### Verification

- Clean isolated baseline: 641 passed, 4 skipped, 62 warnings.
- Red evidence: 2 of 3 new regression tests failed because critical PSI was returned as `BLOCKED` when coverage or mature-outcome evidence was incomplete.
- Post-change suite: 644 passed, 4 skipped, 62 warnings.

## 1.28.0 — 2026-07-06

### Fixed

- Formal experiment/backtest portfolio returns no longer allocate equal notional across simultaneous trades or fixed horizon sleeves while production sizes each plan by stress risk.
- New deterministic accounting allocates equal per-trade stress-risk budgets, preserves open risk until modeled exit, and proportionally scales each simultaneous cohort to remaining `MAX_TOTAL_OPEN_RISK_RATE` and leverage/margin-reserve capacity.
- Hourly nominal and mandatory ×1.5/×2 cost-stress paths use the same risk-budgeted allocation and continue to recognize intrahorizon mark-to-market, funding and terminal costs on observed periods only.
- Experiment evidence exposes risk-, margin- and blocked-allocation counts plus maximum reserved-risk and margin-utilization rates.
- Model promotion policy binding now includes `DEFAULT_RISK_RATE`, `MAX_TOTAL_OPEN_RISK_RATE` and `MARGIN_RESERVE_RATE`, preventing experiment evidence generated for a different sizing policy from authorizing activation.
- Experiment return-path, cost-stress and promotion-policy-binding schemas were raised to risk-budgeted v4/v2/v2 contracts.

### Compatibility

- No database migration, public HTTP API change, `.env` addition, model feature/label/runtime artifact change or recommendation threshold change.
- Already active artifacts remain runnable. Inactive candidates with policy-binding v1 and experiment families with equal-notional v3 paths must be retrained/rerun before normal promotion.
- The accounting remains a research approximation: historical instrument minimums, exact depth/partial fills, operator ordering and profile-specific capital selection are not reconstructed.

### Verification

- Clean isolated baseline: 636 passed, 4 skipped, 62 warnings.
- Red evidence: the new regression module failed collection because risk-budgeted accounting did not exist; the synthetic equal-notional path produced −1.5% while live-style equal-risk sizing produces +0.525%.
- Post-change suite: 641 passed, 4 skipped, 62 warnings.

## 1.27.0 — 2026-07-06

### Fixed

- A persisted `CRITICAL` production-drift report now quarantines the exact active model version instead of only degrading the worker heartbeat.
- The hourly worker evaluates drift after outcome maturation and before inference, preventing one additional decision set from being published after critical drift is observed.
- Signal publication short-circuits before market/profile queries while quarantined and records deterministic `critical_production_drift` attrition for every selected symbol.
- New and recalculated execution plans fail closed to `NO_TRADE`; acceptance of an older actionable plan returns `PLAN_RECALCULATION_REQUIRED` instead of bypassing the quarantine.
- The quarantine is reconstructed from successful persisted drift `JobRun` evidence after restart, cannot be cleared by disabling new monitor jobs, and is released only when a different reviewed model version becomes active.
- Stale runtime or signal versions that do not match the current active model registry fail closed instead of bypassing the old-version quarantine.
- Insufficient-observation `BLOCKED` reports do not latch the publication guard, avoiding a bootstrap deadlock in a monitor that depends on prospective published prediction snapshots.

### Compatibility

- No database migration, public HTTP schema change, `.env` variable, model artifact schema or recommendation threshold change.
- Advisory-only and read-only Bybit boundaries are unchanged; the interlock never places, changes or cancels an order.
- An already active version with any successful persisted `CRITICAL` report for that immutable version is quarantined immediately after upgrade or same-version reactivation. Operator recovery requires activating another governed model version; deleting evidence or silently clearing the latch is not supported.

### Verification

- Clean isolated baseline: 627 passed, 4 skipped, 62 warnings.
- Red evidence: the guard contract was absent on baseline; an acceptance regression also returned HTTP 200 instead of the required 409 before the final conflict-preservation fix.
- Post-change suite: 636 passed, 4 skipped, 62 warnings.

## 1.26.7 — 2026-07-06

### Fixed

- Backtest now emits aligned hourly mark-to-market capital-return paths for the mandatory ×1.5 and ×2 cost-stress scenarios instead of exposing only terminal diagnostic totals.
- Successful experiment events fail closed unless both stress paths use the exact nominal timestamps and reconcile their terminal return and maximum drawdown.
- Experiment governance rejects a statistically admissible selected configuration with `REJECTED_COST_STRESS` when either mandatory scenario compounds below 0%.
- Model promotion report/gate schemas were raised to v4/v3; legacy persisted gate v2 cannot authorize normal activation without passed cost-stress evidence.

### Compatibility

- No database migration, public HTTP API change, model feature/artifact schema change or `.env` addition.
- Trading recommendation thresholds are unchanged. The new non-negative cost-stress terminal-return requirement is an experiment-promotion safety invariant.
- Active artifacts remain active. Existing experiment families whose successful events lack v1 cost-stress paths must rerun preregistered backtests before normal promotion.

### Verification

- Clean isolated baseline: 622 passed, 4 skipped, 62 warnings.
- Red evidence: 2 targeted tests failed before implementation.
- Post-change suite: 627 passed, 4 skipped, 62 warnings.

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
