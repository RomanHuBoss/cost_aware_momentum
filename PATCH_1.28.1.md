# Patch 1.28.1 — critical drift evidence precedence

## Problem

The production drift monitor used a single mutable status with this effective precedence:

```text
OK < WARN < CRITICAL < BLOCKED
```

This made incomplete evidence stronger than independently confirmed critical evidence. For example, a report with feature PSI `11.512865346214785` and alert `feature_distribution_drift` was returned as `BLOCKED` when inference coverage was 60% instead of the required 80%.

The publication quarantine latches only persisted reports whose overall status is `CRITICAL`. Therefore incomplete coverage, warm-up, failed-job or mature-outcome evidence could suppress an independently proven critical shift and leave the active artifact able to publish new recommendations.

## Solution

- Raised the drift report contract to `production-drift-report-v3`.
- Replaced order-dependent status mutation with explicit evidence categories:
  - `critical_evidence`;
  - `blocking_evidence`;
  - `warning_evidence`.
- Overall status is now resolved deterministically:
  - any valid independent critical evidence → `CRITICAL`;
  - otherwise any incomplete/invalid evidence → `BLOCKED`;
  - otherwise warning evidence → `WARN`;
  - otherwise `OK`.
- Failed inference jobs, invalid coverage accounting and incomplete maturity evidence add blockers without overwriting independent critical feature/probability/actionability evidence.
- Incomplete or invalid mature-outcome coverage removes calibration-only `calibration_drift` / `calibration_warning` evidence before final status resolution.
- Empty or sub-minimum warm-up windows do not create a false critical missingness alarm; they remain blocked until the configured denominator exists.

## Compatibility

- Database migration: none.
- Public HTTP API: unchanged.
- `.env`: no new variables or default changes.
- Model feature, label and artifact schemas: unchanged.
- Existing persisted v2 `CRITICAL` reports remain effective because the publication guard is status/model-version based.
- Recommendation thresholds, actionability gates, active artifact and advisory-only/read-only boundaries are unchanged.

## Verification

Baseline:

```text
641 passed, 4 skipped, 62 warnings
```

Red:

```text
python -m pytest -q tests/unit/test_critical_drift_evidence_precedence_2026_07_06.py
2 failed, 1 passed
```

The failing cases showed:

```text
expected CRITICAL, actual BLOCKED
```

Green targeted:

```text
20 passed
```

Full post-change suite:

```text
644 passed, 4 skipped, 62 warnings
```
