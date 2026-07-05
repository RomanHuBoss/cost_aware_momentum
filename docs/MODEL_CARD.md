# Model Card

## Task

Direction-conditional multiclass probability model для hypothetical LONG и SHORT scenarios. Classes: `TP`, `SL`, `TIMEOUT`. `NO TRADE` определяется downstream policy.

## Features

Текущая schema содержит десять OHLCV-derived features и direction code. OI, basis, funding, cross-asset context и liquidity state в model features не входят.

## Temporal protocol, schema v4

Final evaluation использует отдельный chronological train/calibration/final-holdout split с `label_end_time` purge и horizon embargo. До обращения к final holdout development period проходит три fold expanding walk-forward:

- expanding training window;
- rolling calibration window;
- более поздний неперекрывающийся test window;
- новый model/preprocessing/calibration fit в каждом fold;
- целые decision timestamps и неразделимые LONG/SHORT pairs.

Artifact сохраняет:

- `temporal_split_schema=final-holdout-plus-expanding-walk-forward-v4`;
- `walk_forward_schema=expanding-train-rolling-calibration-purged-v1`;
- fold-level time bounds, row counts, ML и policy metrics.

## Entry and labels, schema v3

Decision доступен после close исходной свечи. Entry mid proxy — open следующей hourly свечи. Для приближения executable side применяется adverse half-spread:

- LONG выше mid proxy;
- SHORT ниже mid proxy.

Artifact сохраняет `label_path_schema_version`, execution schema и `entry_spread_bps`.

## Promotion

Auto-activation требует:

- три полных, упорядоченных и неперекрывающихся walk-forward folds;
- допустимый worst-fold log loss и multiclass Brier;
- положительный skill относительно class-prior baseline минимум в двух из трёх folds;
- положительный policy realized mean R минимум в двух из трёх folds;
- отдельные absolute final-holdout calibration/skill/economic gates;
- independent horizon phases, positive lower confidence bound и compatible incumbent comparison.

## Known limitations

Walk-forward фиксирован на трёх folds и не является nested cross-validation, combinatorial purged CV или PBO. Нет historical bid/ask/depth, operator latency, path-dependent fill model, Deflated Sharpe и production drift monitor. Результаты не являются доказательством прибыльности.
