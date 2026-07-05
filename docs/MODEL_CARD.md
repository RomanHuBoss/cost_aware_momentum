# Model Card

## Task

Direction-conditional multiclass probability model для hypothetical LONG и SHORT scenarios. Classes: `TP`, `SL`, `TIMEOUT`. `NO TRADE` определяется downstream policy. Intrahorizon liquidation не является новым ML-классом и не переписывает обучающий target.

## Features

Текущая schema содержит десять OHLCV-derived features и direction code. OI, basis, funding, cross-asset context, mark-price path и liquidity state в model features не входят. Mark-price history используется только для realized OOS margin evidence после формирования ex-ante сценариев.

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

## Historical funding replay, schema v1

Research labels сохраняют фактические funding events для полного горизонта и для modeled actual exit. Settlement window — `(entry_time, exit_time]`: событие на момент входа не списывается повторно, событие на момент выхода учитывается. Positive exchange rate означает отрицательный cash flow LONG и положительный SHORT.

Actual future rates используются только как realized OOS cost. Они не участвуют в выборе направления, expected RR/EV или actionability, потому что не были доступны оператору в decision time. Point-in-time funding forecast пока отсутствует; expected funding source фиксируется как `none-no-point-in-time-forecast`.

Artifact сохраняет `historical_funding_schema=bybit-settlement-timestamp-replay-v1` и summary settlement coverage. Runtime и promotion gate требуют этот contract fail-closed.

## Intrahorizon mark-to-market, schema v1

Release 1.13.0 требует полную hourly mark-price OHLC timeline от entry bar до modeled last-price exit. Для LONG и SHORT отдельно рассчитываются:

- maximum adverse excursion;
- maximum favorable excursion;
- minimum isolated equity rate;
- proxy liquidation flag, bar и open/intrabar marker;
- effective realized exit/PnL и funding settlements до этого выхода.

Схема: `intrahorizon_margin_schema=bybit-mark-price-hourly-isolated-margin-proxy-v1`. Research leverage берётся из `DEFAULT_LEVERAGE`; reserve равен 10% initial margin и является частью immutable contract. Если mark path неполна или assumptions не совпадают, candidate/runtime блокируются fail-closed.

Future mark path не участвует в model fit, class probabilities, direction selection, RR, expected EV или actionability. После ex-ante выбора она может только ухудшить/сократить realized evidence. Target `TP / SL / TIMEOUT` сохраняется для стабильности задачи модели.

Это conservative hourly isolated-margin proxy, а не точная биржевая ликвидация. Нет historical MMR/risk tiers, sub-hour path ordering, liquidation fee, bankruptcy price, cross/portfolio margin, ADL или exact exchange fill mechanics.

## Promotion

Auto-activation требует:

- три полных, упорядоченных и неперекрывающихся walk-forward folds;
- допустимый worst-fold log loss и multiclass Brier;
- положительный skill относительно class-prior baseline минимум в двух из трёх folds;
- положительный policy realized mean R минимум в двух из трёх folds;
- отдельные absolute final-holdout calibration/skill/economic gates;
- independent horizon phases, positive lower confidence bound и compatible incumbent comparison;
- complete historical-funding и intrahorizon-margin evidence;
- одинаковые research leverage/reserve assumptions у candidate, runtime и incumbent comparison.

## Known limitations

Walk-forward фиксирован на трёх folds и не является nested cross-validation, combinatorial purged CV или PBO. Нет historical bid/ask/depth, operator latency, path-dependent fill model, point-in-time funding forecasts, historical funding-interval/risk-tier reconstruction, exact liquidation engine, Deflated Sharpe и production drift monitor. Результаты не являются доказательством прибыльности.
