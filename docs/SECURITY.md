# Security

## Supported security posture

- Advisory-only operation; no implemented order create/amend/cancel/withdraw methods.
- PostgreSQL-only persistence; no hidden SQLite fallback.
- Explicit operator authentication and signed session handling.
- Secrets belong in environment configuration, never in release archives.
- Production configuration must not enable demo or uncalibrated actionable baseline behavior.
- Fail-closed behavior is preferred over silent fallback.

## Release hygiene

Release artifacts must exclude `.env`, credentials, bytecode caches, virtual environments, build outputs, dumps, logs, and real model artifacts. `scripts/release_integrity.py` verifies required release evidence and forbidden artifact absence.

## 1.52.13 note

No new credentials, scopes, Bybit trading permissions, or exchange write endpoints were added.

## 1.52.18 market-data integrity note

Kline/OHLCV rows with impossible price geometry, non-positive prices, negative volume, or non-finite turnover are rejected before persistence. This preserves fail-closed behavior for market facts that feed features, labels, inference, and advisory plans.

## 1.52.19 market-data integrity note

Bybit ordinary `last` kline volume/turnover remain mandatory and fail-closed. Bybit `mark` and `index` klines are price-only endpoints; absent volume/turnover are represented as explicit zero placeholders only for those price types to preserve non-null schema compatibility without misclassifying valid exchange payloads as malformed data.
## 1.52.20 orderbook integrity note

Orderbook validation now rejects locked (`best_ask == best_bid`) as well as crossed (`best_ask < best_bid`) top-of-book states before snapshots can become execution/liquidity evidence. This preserves fail-closed behavior when exchange depth data is internally inconsistent or not safe for conservative execution planning.


## 1.52.21 market-data integrity note

Mark/index kline validation now rejects partial OHLCV-like rows where one optional volume/turnover field is present without the other. This prevents downstream candle facts from combining exchange-provided values with synthetic placeholders except for the explicitly supported fully price-only mark/index shape.
