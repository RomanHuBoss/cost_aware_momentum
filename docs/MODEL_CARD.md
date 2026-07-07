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

## Ограничения

Техническое прохождение gate не является обещанием прибыли. Исторические results подвержены regime change, market impact, execution error и unobserved selection effects. Production требует paper/shadow/forward evidence и операторского контроля.
