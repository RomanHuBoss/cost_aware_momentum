# Patch 1.40.0 — decision-time entry anchoring

Date: 2026-07-07

## Problem

Training labels and live signal construction did not share one immutable entry-timing contract.

Training used the first hourly open after the confirmed decision candle, stressed by half of `MODEL_ENTRY_SPREAD_BPS`. Live inference, however, centered its admissible entry band, stop and target geometry on the latest executable bid/ask. The `last_price` argument was only validated and otherwise unused. Therefore a delayed hourly run or startup catch-up could reuse probabilities produced for an earlier decision boundary while silently rebuilding the trade around a materially different current price.

The former `±0.12 ATR` band did not prevent this because it moved together with the current quote. Signal TTL also began at `publish_time`, allowing a late publication to extend the usable decision window.

## Correction

- Added `ENTRY_ZONE_ATR_FRACTION` with default `0.12`.
- Historical labels now anchor the entry zone to the confirmed decision-candle close.
- Both directionally stressed next-hour-open entries must lie inside the same zone; otherwise the whole LONG/SHORT timestamp pair is excluded.
- Live selection anchors the zone to the exact close of the candle used for model features.
- Both current bid and ask must remain inside that fixed zone before either directional scenario can be evaluated.
- Stop, TP and net economics remain based on the actual executable bid/ask, but only inside the authorized decision-time zone.
- Added `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS=600` and blocked publication beyond that delay.
- Signal expiry is now `event_time + SIGNAL_TTL_MINUTES`, not `publish_time + SIGNAL_TTL_MINUTES`.
- Added decision anchor, entry-zone width and publication-lag evidence to signal diagnostics.
- Promotion-policy binding is now v4 and includes entry-zone width and maximum publication delay.
- Active artifact entry-zone and publication-delay values must exactly match runtime settings; mismatch blocks publication fail-closed.
- Entry-execution artifact schema is now `decision-close-zone-next-hour-open-directional-half-spread-v2`; policy metric schema is v18.

## Compatibility

No database migration is required.

Two new environment variables are documented:

```env
ENTRY_ZONE_ATR_FRACTION=0.12
MAX_SIGNAL_PUBLICATION_DELAY_SECONDS=600
```

Pre-1.40 model artifacts use the old moving-entry research contract and are intentionally rejected by the runtime validator. A new candidate must be trained and must pass all unchanged quality, walk-forward, policy and promotion gates.

Existing persisted signals and plans are immutable historical calculations and are not rewritten.

## Verification

Baseline 1.39.0:

- `755 passed, 8 skipped`.
- New regression suite: `7 failed`.

Release 1.40.0:

- New regression suite: `7 passed`.
- Full suite: `762 passed, 8 skipped`.
- Ruff, compileall and JavaScript syntax: passed.
- Alembic: one unchanged head, `0017_model_artifact_blobs`.

PostgreSQL integration tests were skipped because no isolated PostgreSQL test database was configured. The operator database was not accessed.

## Limitations

Historical bid/ask depth, sub-hour execution path, queue position, partial-fill probability and operator latency within the permitted decision zone remain unavailable. This patch prevents a known re-anchoring error but does not prove profitability or explain every prior loss.
