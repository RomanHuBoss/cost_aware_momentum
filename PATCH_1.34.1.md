# Patch 1.34.1 — Promotion-bound market-signal funding semantics

Date: 2026-07-06

## Problem

The candidate quality/promotion path evaluates ex-ante policy with `policy_expected_funding_source=none-no-point-in-time-forecast` and an immutable `funding_rate_override=0`, because the repository does not contain historical point-in-time funding forecast snapshots. Live signal publication nevertheless projected the current ticker funding rate and passed it into LONG/SHORT ranking.

That made deployed direction depend on a cost input absent from final-holdout evidence. A deterministic reproduction with equal LONG/SHORT probabilities, equal executable prices and zero other costs selected LONG with the promotion policy but SHORT when positive live funding was injected. The model artifact was unchanged; only the unvalidated live overlay changed direction.

## Solution

- Added the shared constant `POLICY_EXPECTED_FUNDING_SOURCE` used by training metrics, lifecycle validation and signal publication.
- `select_cost_aware_scenario` now rejects non-zero expected funding fail-closed.
- `publish_hourly_signals` ranks and persists market-signal economics with zero expected funding, exactly matching promotion evidence.
- The current ticker projection is retained in `feature_snapshot.economics_assumptions` as execution evidence rather than mixed into direction selection.
- Execution-plan creation and acceptance continue to project fresh funding independently and conservatively. Adverse funding still increases downside, reduces net R/R and EV, can shrink size, produce `NO_TRADE`, or reject stale acceptance.

## Compatibility

- No database migration; Alembic head remains `0016_universe_replay_asof`.
- No `.env` changes.
- No HTTP or frontend schema change.
- No model artifact, feature or label schema change.
- Existing active artifacts remain loadable; restart worker/API to apply the corrected policy layer.
- No new dependency.

## Red → green evidence

Before the fix:

```text
test_market_signal_policy_rejects_unvalidated_expected_funding_overlay
Failed: DID NOT RAISE ValueError

test_signal_policy_uses_the_exact_model_atr_without_hidden_clipping
AssertionError: Decimal('0.001') != Decimal('0')
```

After the fix:

```text
2 passed
```

## Limitations

- Historical point-in-time funding forecasts are still unavailable.
- Signal-level economics therefore use zero expected funding until a versioned, historically reproducible forecast policy is implemented and re-evaluated.
- Execution plans can be stricter than market signals because they use current adverse funding, orderbook, account and portfolio state.
- The patch does not increase recommendation frequency and does not establish economic profitability.
