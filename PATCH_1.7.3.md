# Patch 1.7.3 — immediate bootstrap/recovery training

## Problem

The 1.7.2 worker safely fell back to the deterministic baseline when the active model artifact was missing, but the trainer scheduler still treated the stale registry row as a normal trained model. Recovery could therefore wait for dataset-change thresholds or inherit a six-hour cooldown from an unrelated failed retraining job.

## Change

- Missing active artifact now creates `bootstrap_recovery` before normal dataset-aware scheduling.
- No active model or active deterministic baseline creates `bootstrap_training`.
- Both triggers start after the configured startup delay once history and coverage requirements pass.
- Unrelated prior scheduled/data-change jobs do not delay a new bootstrap episode.
- Repeated technical failures for the same bootstrap episode use `AUTO_TRAIN_RECOVERY_RETRY_MINUTES` (default 15).
- A candidate rejected by quality gates remains inactive and uses the controlled data-change cooldown, avoiding a tight fitting loop.
- Existing advisory lock, immutable candidate, absolute gates, guarded activation and production fail-closed behavior are unchanged.

## Compatibility

No migration is required. Existing `.env` files remain valid because the new setting has a safe default. Add this line to make the behavior explicit:

```env
AUTO_TRAIN_RECOVERY_RETRY_MINUTES=15
```
