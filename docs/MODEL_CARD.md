# Model Card

## Назначение

Direction-conditional модель оценивает исходы `TP / SL / TIMEOUT` отдельно для LONG и SHORT hourly scenarios. `NO TRADE` — решение policy layer, а не класс модели.

## Входы

- confirmed hourly OHLCV-derived features;
- point-in-time OI, mark/index basis, funding state и liquidity context;
- исторически действовавшие instrument specs;
- temporal availability и continuity evidence.

## Выходы

Калиброванные probabilities для трёх исходов и conditional TIMEOUT return estimate. Market policy выбирает направление по net EV/R и RR с текущей исполнимой bid/ask geometry; execution layer отдельно применяет капитал, funding overlay, margin, liquidity и portfolio caps.

## Validation

- group-preserving chronological split с purge/embargo;
- untouched final holdout;
- expanding walk-forward development folds;
- calibration, class coverage и prior-skill gates;
- opportunity-weighted policy evidence, overlap control, horizon phases, bootstrap LCB;
- direction/symbol/cluster/regime robustness;
- immutable artifact hash/schema/classes/horizon checks.

## Cold-start provenance

На чистой dynamic-базе первый artifact может иметь mode `historical_frozen_dynamic_bootstrap`. Его cohort связан с текущим свежим universe snapshot, но не считается точной historical membership. Для pre-observation instrument specs используется earliest locally observed tick с adverse extra-tick stress. После накопления достаточного ledger создаётся `prospective_dynamic_replay` replacement candidate.

## Ограничения

Техническое прохождение gate не является обещанием прибыли. Historical bootstrap сохраняет current-cohort selection/survivorship limitation; архивные bid/ask/depth, queue position и local receipt times не реконструируются. Исторические results подвержены regime change, market impact, execution error и unobserved selection effects. Production требует paper/shadow/forward evidence и операторского контроля.
