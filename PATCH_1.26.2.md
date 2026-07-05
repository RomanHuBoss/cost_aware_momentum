# Patch 1.26.2 — deferred governed model promotion

## Problem

A fresh background artifact is immutable and receives a unique version/SHA-256. Exact preregistered experiment evidence normally cannot be complete in the same training call. The trainer registered a quality-passed candidate as inactive, but later scheduling iterations never revisited it. Consequently `AUTO_TRAIN_AUTO_ACTIVATE=true` did not complete the documented staged lifecycle after the operator produced matching `READY` evidence.

## Solution

- Added discovery of the newest inactive background candidate with `activation_requested=true` and a valid persisted quality gate.
- Added periodic re-evaluation of `AUTO_TRAIN_EXPERIMENT_FAMILY` against the candidate's exact version, SHA-256 and horizon.
- Added deferred activation through a shared transaction boundary that rechecks the experiment family under lock, validates artifact bytes/runtime metadata, detects active-version races, updates the registry and writes audit/outbox events atomically.
- Kept non-READY, missing, malformed or mismatched evidence fail-closed.
- Prevented a second training run in the same scheduling iteration after successful promotion.

## Configuration

After a quality-passed candidate has been registered, preregister the experiment family for that exact artifact and set:

```env
AUTO_TRAIN_EXPERIMENT_FAMILY=<family>
```

Restart the trainer so the setting is loaded. Empty configuration leaves the candidate inactive. `ACTIVE_MODEL_PATH` continues to disable registry auto-promotion.

## Migration and compatibility

- Database migration: none.
- Artifact schema: unchanged.
- Public API: unchanged.
- Existing inactive candidates remain compatible when their registry metrics contain a valid passed quality gate and artifact SHA-256.

## Tests

- `tests/unit/test_deferred_model_promotion.py`
- Existing activation-governance tests were redirected to the shared production activation service without weakening their assertions.
