# Patch 1.26.3 — experiment-to-deployment policy binding

## Problem

`model-promotion-experiment-governance-v1` связывал selected preregistered trial с exact model version, artifact SHA-256 и horizon, но не проверял policy parameters, которые определяли сам backtest. Family могла выбрать trial с более низкими fees/slippage, меньшим stop-gap reserve или более мягкими EV/RR thresholds. Activation при этом меняла только active artifact, а production использовала текущие настройки. Следовательно, `READY` report мог подтверждать другую торговую стратегию.

## Solution

- Added immutable `model-promotion-policy-binding-v1` candidate metadata.
- Bound entry spread, leverage/reserve, fees, slippage, stop-gap reserve, funding/timeout overrides, EV/RR thresholds, policy source and portfolio accounting.
- Raised promotion gate to `model-promotion-experiment-governance-v2`.
- Compared selected `STARTED.configuration` with the exact binding and emitted per-key fail-closed reasons.
- Revalidated persisted binding against current deployment settings in fresh, deferred and registry activation paths.
- Kept quality gate, artifact hash/runtime validation, incumbent compare-and-swap, audit and outbox semantics unchanged.

## Compatibility and operator action

- Database migration: none.
- `.env` additions: none.
- Public HTTP API: unchanged.
- Artifact runtime schema: unchanged; new candidate metrics include the binding.
- Already active artifacts remain active and runnable.
- Inactive candidates trained before 1.26.3 lack the binding and cannot use normal activation. Retrain the candidate and rerun the preregistered experiment family. An explicit reasoned emergency rollback remains available for reviewed incidents.
- If fees, slippage, stop-gap reserve, leverage/reserve or EV/RR thresholds change after experiment evidence is produced, generate new governed evidence under the new policy.

## Verification

- Baseline: 609 passed, 4 skipped, 61 warnings.
- Red evidence: 2 failed because `evaluate_experiment_promotion_gate` had no `expected_policy_binding` contract.
- Green targeted evidence: 4 passed in `test_experiment_policy_binding_2026_07_05.py`.
- Full post-change suite: 613 passed, 4 skipped, 61 warnings.
- Ruff, compileall, pip check and JavaScript syntax: passed.
- PostgreSQL integration: not run because a separate test database was not configured.

## Limitations

This patch prevents evidence/configuration substitution. It does not prove profitability, reconstruct historical order books or point-in-time funding forecasts, automate experiment-family execution, or change risk thresholds.
