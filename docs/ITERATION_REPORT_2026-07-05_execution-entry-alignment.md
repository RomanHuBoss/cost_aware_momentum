# Iteration Report — execution-entry alignment

## 1. Input

- Archive: `cost_aware_momentum-main.zip`
- SHA-256: `fafa4976e662cf7d0ee6d1998fe9d2e29584f6690d82357f219d6f9504e6aa10`
- Original version: 1.9.7
- Python requirement: >=3.12
- Database migrations: `0001`–`0009`; no migration added
- Original file inventory: 71 production/maintenance Python files including `manage.py`, 59 test Python files, 1 documentation file (source DOCX)
- Unexpected release artifacts in input: none found (`.env`, credentials, caches, virtualenv, build output, real model artifacts and dumps absent)

The archive did not contain `CHANGELOG.md`, `PATCH_*.md`, `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md` or the operational documents named by the supplied iteration protocol. This was treated as a release/documentation gap, not as evidence that old versions never had those documents.

## 2. Goal and acceptance criteria

Goal:

> After this iteration, historical LONG/SHORT labels, candidate artifacts, promotion gates and research backtests must share one explicit direction-specific entry execution model, preventing frictionless next-hour-open labels from being compared with live ask/bid execution.

Acceptance criteria:

1. LONG entry is above next-hour open by half of configured full spread.
2. SHORT entry is below next-hour open by half of configured full spread.
3. The first path bar cannot include price movement that occurred before modeled entry.
4. Spread must be finite and non-negative.
5. Trainer, manual train CLI and backtest propagate the same spread semantics.
6. Artifact/runtime and auto-activation gate reject missing, legacy or inconsistent execution metadata.
7. Candidate/incumbent evaluation is skipped when entry/barrier geometry is incompatible.
8. Existing advisory-only, PostgreSQL-only and fail-closed boundaries remain unchanged.

## 3. Sources read and data flow

Read:

- `README.md`, `pyproject.toml`, `.env.example`;
- source specification `docs/source/Cost_aware_hourly_ML_momentum_specification.docx` in relevant execution, validation and econometric sections;
- uploaded iterative-development protocol;
- production modules for features, labels, training, lifecycle, runtime, trainer, signals, execution, Bybit reads, PostgreSQL models and backtest;
- unit and PostgreSQL integration test trees.

No prior changelog, patch notes, QA/compliance/traceability files existed in the input archive.

Changed flow:

`confirmed hourly candles → point-in-time features → next-hour open mid proxy → direction-specific half-spread entry → TP/SL/TIMEOUT labels → purged split → candidate metrics/artifact → quality gate/runtime → research backtest`.

## 4. Baseline

After installing the declared editable dev dependencies:

- `python -m pip check`: FAILED only because host `moviepy 2.2.1` conflicts with host `pillow 12.2.0`.
- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: 461 passed, 4 skipped.
- `node --check web/js/app.js`: PASSED.
- PostgreSQL integration: NOT RUN; no isolated test DB.

## 5. Confirmed defects and gaps

### 5.1 CONFIRMED DEFECT — critical — fixed in this iteration

**Location:** `app/ml/training.py::make_barrier_dataset`; contrasted with `app/services/signals.py`.

**Actual behavior:** production used ask for LONG and bid for SHORT, while both historical directional scenarios used the same first next-hour `open` as entry.

**Impact:** entry price, ATR-scaled barrier prices, TP/SL/TIMEOUT class, realized return, calibration evidence and policy economics were biased toward frictionless execution. Candidate/incumbent comparison could also use labels with different execution assumptions.

**Why tests missed it:** tests validated decision-time open vs previous close, temporal purge and directional geometry, but did not assert an adverse executable-side offset between LONG and SHORT.

### 5.2 CONFIRMED GAP — high — residual

Historical bid/ask, depth, VWAP impact, no-fill and partial-fill are absent. `app/bybit/client.py::get_orderbook` reads only a current snapshot; no historical orderbook table or fill simulator exists. The 1.10.0 spread proxy is explicit stress, not reconstruction.

### 5.3 CONFIRMED GAP — high — residual

Historical funding exists as a PostgreSQL entity and live plans project settlements, but training/policy backtest uses a scalar funding scenario rather than joining every historical settlement by event and availability timestamps.

### 5.4 CONFIRMED GAP — high — residual

`chronological_split()` implements one purged train/calibration/final-holdout split. Rolling/expanding walk-forward is absent.

### 5.5 CONFIRMED GAP — high — residual

Counterfactual outcome storage reduces “only accepted trades” blindness, but no causal/operator-selection model, propensity weighting or missing-not-at-random correction exists.

### 5.6 CONFIRMED GAP — high — residual

Research backtest explicitly states that intrahorizon mark-to-market is not modeled. A static pre-trade liquidation-distance guard exists, but path-dependent liquidation simulation does not.

### 5.7 CONFIRMED GAP — high — residual

`app/ml/features.py::FEATURE_NAMES` contains ten OHLCV-derived features. Stored OI/funding and broader basis/liquidity/market-context variables are not part of model input.

### 5.8 CONFIRMED GAP — medium — residual

PBO and Deflated Sharpe are absent. Immutable artifacts/model registry/backtest records provide a partial experiment ledger, not a complete multiple-testing ledger.

### 5.9 CONFIRMED GAP — medium — residual

No production feature/calibration/PSI drift monitor or drift-based block/alert path was found.

### 5.10 DOCUMENTED LIMITATION — not a defect

A model trained from roughly one day of observations cannot pass defaults that require at least 300 unique labeled timestamps for splitting and a 168-hour final holdout span; README computes a default minimum near 1206 hourly timestamps before gaps. Gates were intentionally not weakened.

The externally claimed counts of “15 + 8 critical and 4 medium” could not be independently substantiated because no module list, reproduction or report was supplied. This iteration reports only evidenced findings.

## 6. Implementation

Production:

- `app/ml/training.py`: direction-specific entry proxy, path normalization, schema v3/v13, execution metadata.
- `app/config.py`: `model_entry_spread_bps=18.0`, finite/non-negative validation.
- `app/ml/lifecycle.py`: propagation into dataset/artifact, gate validation, incumbent compatibility.
- `app/ml/runtime.py`: fail-closed artifact execution schema and spread consistency.
- `app/workers/trainer.py`, `scripts/train.py`: pass configured spread.
- `scripts/backtest.py`: use artifact spread and record it in run config.
- `.env.example`: document parameter and limitations.

Tests:

- New `tests/unit/test_execution_aware_training_entry_2026_07_05.py`.
- Updated artifact fixtures and current policy-schema fixtures.
- Added gate/runtime consistency assertions.

Documentation/version:

- Version bumped 1.9.7 → 1.10.0.
- Added changelog, patch notes and required operational/compliance documents.

## 7. Red → green evidence

Red command:

```text
python -m pytest -q tests/unit/test_execution_aware_training_entry_2026_07_05.py
```

Before implementation: 2 failed with unexpected `entry_spread_bps` argument.

After implementation: 3 passed. Additional targeted gate/runtime suites passed before the full suite.

## 8. Compatibility

- DB migration: none.
- Public HTTP API: unchanged.
- Environment: one new optional variable with default `18`.
- Artifact compatibility: intentionally incompatible with old label/execution schemas. Retraining is required; runtime fails closed.
- Rollback risk: returning to 1.9.7 requires reactivating an artifact compatible with 1.9.7. A 1.10.0 artifact should not be assumed compatible with older runtime.

## 9. Post-check

- `python -m compileall -q app scripts tests manage.py`: PASSED.
- `python -m ruff check .`: PASSED.
- `python -m pytest -q`: 468 passed, 4 skipped.
- `node --check web/js/app.js`: PASSED.
- `python -m pip check`: FAILED due unchanged external host `moviepy`/`pillow` conflict.
- Integration tests: 4 SKIPPED because `TEST_DATABASE_URL` is unset.
- `python manage.py doctor`: environment failure because `.venv` is absent; no configured runtime smoke claim is made.

## 10. Not verified

- PostgreSQL migration upgrade/clean-db integration in a dedicated test database.
- Bybit network/API behavior against current external service.
- Training on a real 365-day dataset and candidate gate outcome.
- Paper/shadow forward performance and profitability.
- Historical spread calibration by symbol/regime.

## 11. Residual risks

A fixed 18 bps full-spread stress may be conservative for liquid symbols and optimistic for illiquid/volatile regimes. It does not model operator reaction delay, depth or fills. Strategy losses can persist because execution alignment removes one source of optimism but does not create predictive edge.

## 12. Rollback

1. Stop API/worker/trainer.
2. Restore source version 1.9.7.
3. Restore or reactivate the previously compatible 1.9.7 artifact and registry state.
4. Remove `MODEL_ENTRY_SPREAD_BPS` only if desired; it is ignored by 1.9.7.
5. Run doctor and paper/shadow checks before resuming.

No database downgrade is required.

## 13. Recommended next work package

Implement historical funding settlement alignment in dataset and policy backtest: point-in-time join `market.funding` by actual settlement timestamps, direction-signed cash flow only when the modeled position crosses a settlement, with tests for availability time, multiple settlements and no-settlement horizons.

## 14. Release archive verification

The clean staged release contained 169 eligible files. `SHA256SUMS` generation and fail-closed verification passed for 169/169 entries. `unzip -t` passed. A fresh extraction passed the full test suite (468 passed, 4 skipped), compileall, Ruff and Node JavaScript syntax checks. The archive contains one root directory and excludes caches, virtual environments, `.env`, credentials, runtime model artifacts and database dumps.
