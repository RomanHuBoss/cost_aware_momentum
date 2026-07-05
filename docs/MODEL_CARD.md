# Model Card

## Task

Direction-conditional multiclass probability model для hypothetical LONG и SHORT scenarios. Classes: `TP`, `SL`, `TIMEOUT`. `NO TRADE` определяется downstream policy.

## Features

Текущая schema содержит десять OHLCV-derived features и direction code. OI, basis, funding, cross-asset context и liquidity state в model features не входят.

## Temporal protocol

Один chronological train/calibration/final-holdout split с label-end purge и hourly embargo. Preprocessing обучается на train. Это не rolling/expanding walk-forward.

## Entry and labels, schema v3

Decision доступен после close исходной свечи. Entry mid proxy — open следующей hourly свечи. Для приближения executable side применяется adverse half-spread:

- LONG выше mid proxy;
- SHORT ниже mid proxy.

Artifact сохраняет:

- `label_path_schema_version=decision-open-directional-spread-entry-ohlc-path-v3`;
- `entry_execution_model.schema=directional-half-spread-on-next-hour-open-v1`;
- `entry_spread_bps`.

## Promotion

Auto-activation требует absolute calibration/skill/economic gates, independent horizon phases, positive lower confidence bound и compatible incumbent comparison. Несовместимый artifact блокируется.

## Known limitations

Нет historical bid/ask/depth, operator latency, path-dependent fill model, rolling walk-forward, PBO/Deflated Sharpe и production drift monitor. Результаты не являются доказательством прибыльности.
