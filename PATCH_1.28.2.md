# Patch 1.28.2 — point-in-time training universe integrity

## Problem

Dynamic background training selected up to `AUTO_TRAIN_MAX_SYMBOLS` from the most recent `TickerSnapshot.turnover_24h`, then applied that present-day cross-section to the full historical lookback.

This created two coupled defects:

1. **Post-cutoff selection information.** A latest 24-hour turnover observation can occur after the label cutoff for historical rows and therefore cannot be used to define a purportedly point-in-time historical cohort.
2. **Coverage instability.** Newly active high-turnover contracts could replace mature contracts despite having fewer than `AUTO_TRAIN_MIN_BARS_PER_SYMBOL`. The preflight profile could consequently fail `AUTO_TRAIN_MIN_SYMBOL_COVERAGE_RATIO`, or the ranking could change between preflight and fit so that the trained dataset no longer matched the trigger profile.

The defect could block model training for operationally irrelevant reasons and could contaminate holdout evidence through ex-post symbol selection. It does not by itself prove that any past trade loss was caused by this path.

## Solution

- Dynamic symbol selection no longer reads `TickerSnapshot`.
- The selection anchor is the latest confirmed hourly last-price candle.
- Candidate symbols must:
  - have at least `AUTO_TRAIN_MIN_BARS_PER_SYMBOL` confirmed rows inside the configured lookback;
  - use only rows at or before `latest_candle - horizon`;
  - have a latest eligible candle reaching that label cutoff.
- Eligible symbols are ranked deterministically by eligible row count, latest eligible candle and symbol name.
- `None` now means unrestricted selection, while an explicit empty symbol list remains empty and fails closed instead of silently loading all symbols.
- Background training reuses the exact symbol list persisted in the trigger `training_data_profile`; it does not re-resolve a moving dynamic universe before fit.
- Manual training passes the same horizon and minimum-history contract into data loading.

## Compatibility

- Database migration: none.
- Public HTTP API: unchanged.
- `.env`: no new variables or default changes.
- Model feature, label and artifact schemas: unchanged.
- Risk, cost, actionability and activation thresholds: unchanged.
- Existing active artifacts remain runnable. A new candidate should be trained to obtain evidence generated with the corrected cohort-selection contract.

## Verification

Baseline:

```text
644 passed, 4 skipped, 62 warnings
```

Red:

```text
python -m pytest -q tests/unit/test_training_universe_integrity_2026_07_06.py
1 failed
actual dynamic selection: ['HOT_NEW_USDT']
expected label-eligible history cohort: ['BTCUSDT', 'ETHUSDT']
```

Green targeted:

```text
1 passed
```

Full post-change suite:

```text
645 passed, 4 skipped, 62 warnings
```
