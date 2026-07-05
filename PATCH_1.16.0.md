# Patch 1.16.0 — point-in-time market-context features

## Problem

The market model still used only ten OHLCV-derived features although the project already stored parts of funding and OI state. It omitted open-interest momentum, perpetual/index basis, settled funding state and a liquidity/participation proxy. A naive addition could also introduce future-event leakage, silent gap filling or unproven feature inflation.

## Solution

- Added strict hourly context construction from last/mark/index candles, open interest and actual settled funding.
- Added seven features: OI log changes 1h/24h, basis and 1h basis change, settled funding rate/age, turnover/OI notional ratio.
- Exact OI/basis and valid prior funding are mandatory; missing/duplicate/non-finite rows fail closed.
- Added progressive index-price and OI history backfill and current mark/index/funding/OI refresh.
- Live inference applies stored receipt-time cutoff; historical public replay explicitly does not claim reconstructed local receipt times.
- Added same-split independent core-feature ablation on final holdout and every walk-forward fold.
- Added artifact/runtime schemas and activation gates for context integrity and non-inferiority.

## Compatibility

- No PostgreSQL migration. Alembic head remains `0011_selection_experiment`.
- No new environment variable names.
- Recommended/default `UNIVERSE_SYNC_MARK_PRICE` and `UNIVERSE_ENRICH_FUNDING_OI` are now `true`; existing `.env` files must be updated manually.
- Pre-1.16 artifacts are intentionally incompatible and require retraining after context backfill.

## Verification

- Red: new regression module failed on 1.15.0 with `ModuleNotFoundError: No module named 'app.ml.context'`.
- Green: context regression module passes, followed by the full project suite and static checks.
- PostgreSQL integration remains dependent on a separate `TEST_DATABASE_URL`.

## Limitations

Historical public APIs do not reconstruct the local receipt timestamp that existed at each old decision. Settled funding is a state feature, not a point-in-time funding forecast. The liquidity feature is a turnover/OI proxy, not historical orderbook depth. Cross-asset context, richer regimes, PBO/Deflated Sharpe and production drift monitoring remain separate work packages.
