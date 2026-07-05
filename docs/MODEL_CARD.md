# Model Card

## Task

Direction-conditional multiclass probability model для hypothetical LONG и SHORT scenarios. Classes: `TP`, `SL`, `TIMEOUT`. `NO TRADE` определяется downstream policy. Intrahorizon liquidation не является новым ML-классом и не переписывает обучающий target.

## Features, schema v4

Artifact model использует 17 ex-ante base features и direction code:

- 10 существующих OHLCV-derived features;
- `oi_log_change_1h`, `oi_log_change_24h`;
- `basis_bps`, `basis_change_1h_bps` по hourly mark/index close;
- `settled_funding_rate`, `funding_age_fraction` только по последнему уже состоявшемуся settlement;
- `turnover_oi_log_ratio` как ограниченный liquidity/participation proxy.

Schema: `hourly-barrier-market-context-v4`; context schema: `hourly-oi-basis-settled-funding-turnover-v1`. Exact OI/basis rows обязательны, funding join только backward, missing/duplicate/non-finite input блокирует timestamp. Historical public replay опирается на exchange event/close timestamps и не утверждает reconstruction локального receipt time; live inference дополнительно фильтрует `available_at`.

Context ablation: на тех же train/calibration/test timestamps независимо переобучается comparator с нулевыми context columns. Final holdout допускает не более 0.005 ухудшения log loss; минимум два из трёх walk-forward folds должны быть non-inferior. Это защита от декоративного расширения признаков, а не доказательство устойчивого edge.

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

## Live advisory execution evidence, schema v1

Release 1.14.0 не добавляет orderbook features в market model и не изменяет artifact schema. После ex-ante model/policy direction account-dependent execution layer использует prospective public REST snapshot:

- LONG потребляет asks, SHORT — bids;
- размер ограничивается bounded depth внутри `MAX_VWAP_IMPACT_BPS`;
- entry для risk/EV/qty пересчитывается по complete-fill VWAP;
- `PARTIAL` и `NO_FILL` блокируются;
- acceptance повторяет simulation для всей qty на новом snapshot;
- plan и decision сохраняют source/receipt times, sequence, VWAP, worst price, impact и operator latency.

Схема evidence: `bybit-rest-depth-vwap-fill-v1`. Это prospective execution-quality evidence, не historical training feature и не подтверждение реального fill. RPI liquidity, queue position, order type, network/decision latency distribution и OMS partial-fill lifecycle отсутствуют.

## Operator-selection diagnostics 1.15.0

Selection model не является market model и не влияет на signal probabilities, direction, RR, EV, sizing или activation. Это отдельный retrospective reporting model, обучаемый только на ранее созданных plan opportunities и только для оценки различий между accepted subset и всеми eligible plans. Outcome не входит в propensity features. Все propensity predictions для оцениваемого блока строятся на более ранних наблюдениях.

Поскольку counterfactual outcomes доступны и для непринятых plans, primary benchmark — прямое среднее всех eligible valued opportunities. IPSW accepted-only estimate служит проверяемой диагностикой selection bias. Отчёт не доказывает causal operator skill, actual fill profitability или отсутствие unmeasured confounding.

## Production drift reference and monitoring 1.17.0

Every artifact persists a reference derived only from its untouched final holdout:

- fixed quantile-bin histograms for all 17 base features;
- fixed histograms for TP/SL/TIMEOUT probabilities across both hypothetical directions;
- log-loss and multiclass Brier for the policy-selected direction only;
- selected-plan actionability density and the RR/EV thresholds used to define it.

Production monitoring uses only signals emitted by the same active model version. Feature/probability PSI, missingness and inference coverage are available immediately; calibration evidence appears only after `SignalOutcome` resolution. Failed inference jobs, inadequate samples or corrupt/incompatible reference produce `BLOCKED`. Critical distribution/calibration/actionability drift produces `CRITICAL` and degrades the worker heartbeat.

The monitor does not alter artifacts or registry state and cannot bypass promotion gates. PSI and delayed calibration are diagnostics, not proof of causal deterioration or profitability.

## Promotion

Auto-activation требует:

- три полных, упорядоченных и неперекрывающихся walk-forward folds;
- допустимый worst-fold log loss и multiclass Brier;
- положительный skill относительно class-prior baseline минимум в двух из трёх folds;
- положительный policy realized mean R минимум в двух из трёх folds;
- отдельные absolute final-holdout calibration/skill/economic gates;
- independent horizon phases, positive lower confidence bound и compatible incumbent comparison;
- complete historical-funding, market-context/ablation и intrahorizon-margin evidence;
- одинаковые research leverage/reserve assumptions у candidate, runtime и incumbent comparison.

## Known limitations

Walk-forward фиксирован на трёх folds и не является nested cross-validation, combinatorial purged CV или PBO. Forward orderbook/latency evidence начинает накапливаться только с 1.14.0 и пока не входит в training/backtest; pre-1.14 historical depth, RPI/queue/limit-order fill model и реальный partial-fill lifecycle отсутствуют. Также отсутствуют historical receipt-time reconstruction, point-in-time funding forecasts, orderbook-depth/cross-asset model features, historical funding-interval/risk-tier reconstruction, exact liquidation engine, Deflated Sharpe, multivariate drift tests, adaptive control limits и automatic drift rollback. Результаты не являются доказательством прибыльности.
