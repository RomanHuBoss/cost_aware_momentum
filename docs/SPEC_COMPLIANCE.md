# Specification Compliance

Состояние на 2026-07-07. Статусы основаны на фактическом коде release 1.50.0, а не на заявлении о полной реализации спецификации.

| Требование | Статус | Доказательство / ограничение |
|---|---|---|
| Advisory-only, read-only Bybit | Реализовано | `app/bybit/client.py` содержит GET market/account reads; order mutation methods отсутствуют. |
| PostgreSQL-only | Реализовано | SQLAlchemy/PostgreSQL models и Alembic; SQLite fallback отсутствует. |
| Reproducible clean PostgreSQL migration chain | Исправлено 1.49.1; live confirmation pending | `0001_initial` создаёт current metadata, поэтому overlap revisions `0006`, `0007`, `0017` теперь guard-ят уже существующие objects, сохраняют данные и повторно утверждают constraints/defaults. Unit regression и PostgreSQL offline SQL прошли; фактический rerun на изолированной PostgreSQL в build environment не выполнялся. |
| Durable immutable model artifacts | Реализовано 1.36.0 | Exact bytes каждого нового candidate, version, SHA-256 и size атомарно сохраняются в `model.model_artifact_blobs`; UPDATE/DELETE запрещены trigger. Worker/trainer/activation service архивируют surviving legacy file или SHA-verified атомарно восстанавливают runtime copy до selection/activation. Уже удалённый pre-1.36.0 artifact без другой копии не реконструируется. |
| Point-in-time confirmed hourly data | Реализовано | `Candle.close_time`, `available_at`, confirmed semantics, temporal tests. |
| Point-in-time dynamic training cohort | Реализовано prospectively 1.31.0; executable-spread alignment 1.37.0; immutable preflight scope 1.38.0 | Каждый training/backtest `symbol × decision_time` допускается только по latest immutable snapshot с `recorded_at <= decision_time`; full snapshot hashes и `dynamic` mode повторно проверяются. Release 1.37.0 пересекает broad membership с точным live `MAX_SPREAD_BPS`. Release 1.38.0 заставляет background fit использовать exact symbols из persisted preflight profile и ограничивает last/mark/index raw history верхней границей `profile.end_time + horizon`; quality gate повторно сверяет symbol scope, temporal cutoff и post-feature coverage. Pre-ledger rows исключаются; stale/missing/corrupt evidence блокирует run. Exact membership до начала ledger и static-mode historical spread cohort не реконструируются. |
| LONG/SHORT executable-side entry semantics | Частично реализовано 1.10.0; decision-time anchoring 1.40.0 | Direction-specific adverse spread proxy сохранён. Release 1.40.0 фиксирует entry zone вокруг close подтверждённой decision candle, требует попадания historical next-hour executable proxy и live bid/ask в один ATR-масштабированный диапазон, блокирует позднюю publication и отсчитывает TTL от event time. Exact historical bid/ask, queue position, sub-hour path и operator latency distribution отсутствуют. |
| Historical orderbook depth/VWAP/no-fill/partial-fill | Частично реализовано 1.14.0; latest-prior live selection исправлен 1.35.4 | Forward point-in-time REST snapshots сохраняются в PostgreSQL; plan/acceptance используют direction-aware bounded-depth simulation, complete-fill VWAP и FULL/PARTIAL/NO_FILL evidence. Live lookup фильтрует `source_time` и `received_at` по exact decision cutoff до сортировки. Исторический backfill до 1.14.0, RPI/queue position, limit-order fill probability и реальный partial-fill lifecycle отсутствуют; поэтому model/backtest gap не считается закрытым. |
| Historical funding tied to actual settlements in research labels | Реализовано 1.22.0 для observed settlement и interval history; deployment alignment усилен 1.34.1 | Progressive backfill сохраняет фактические settlement timestamps; training/backtest агрегируют только события `(entry, actual_exit]`, используют interval, действовавший по `InstrumentSpecHistory`, и fail-closed при пропусках. Будущая фактическая ставка не участвует в ex-ante selection. До появления historical point-in-time forecast snapshots market-signal selector также обязан использовать нулевой expected funding; свежий ticker projection применяется только как более строгий execution-plan/acceptance overlay и не может менять направление. |
| Rolling/expanding walk-forward | Реализовано 1.11.0 | Три purged expanding folds внутри development period, fresh fit/calibration на каждом fold и отдельный final holdout. Не является nested CV/PBO. |
| Operator-selection bias correction | Частично реализовано 1.21.0 | Prospective ex-ante opportunity ledger, immutable first UI-exposure evidence и ACCEPT/REJECT/NO_DECISION сохранены. Denominator теперь включает только plan versions, действительно показанные first-party UI после ≥50% видимости в активной вкладке в течение ≥1 секунды; exposure time задаёт chronological ordering, coverage/anomalies публикуются и низкое coverage блокирует IPSW. Signal-atomic OOS propensity split и cluster moving-block intervals сохранены. Это не causal treatment model: eye tracking, comprehension, latent operator state, propensity refit внутри bootstrap, API/CLI exposures и pre-1.15 opportunities отсутствуют. |
| Intrahorizon MTM and liquidation simulation | Частично реализовано 1.26.6 | Training/backtest требуют exact hourly Bybit mark-price path, рассчитывают directional MAE/MFE/minimum equity и conservative isolated-margin liquidation proxy с actual funding timing. Release 1.26.6 дополнительно сохраняет полный cumulative hourly mark-close MTM/funding path до effective exit и использует его в capital drawdown и experiment-selection returns; future path остаётся realized-only и не влияет на ex-ante direction ranking. Не реализованы sub-hour ordering, historical MMR/risk tiers, liquidation fees, cross/portfolio margin, ADL и точная exchange fill/liquidation mechanics. |
| Policy-path metadata preserved through temporal splits | Реализовано 1.26.6 | Historical funding, intrahorizon margin and cumulative hourly MTM columns generated by the label builder are preserved in train/calibration/final-holdout and expanding walk-forward metadata. Missing, malformed, non-hourly or terminally inconsistent MTM paths fail closed before experiment evidence. Model feature matrices remain unchanged, so realized future paths do not leak into fitting or directional ranking. |
| Risk-budgeted experiment portfolio accounting | Реализовано 1.28.0 | Nominal и cost-stress experiment paths распределяют simultaneous cohort по одинаковому stress-risk budget, сохраняют абсолютный open-risk reserve до exit и пропорционально ограничивают новые entries остатком `MAX_TOTAL_OPEN_RISK_RATE` и leverage/margin-reserve capacity. Evidence раскрывает risk/margin limiting и exact policy binding. Historical min order, depth, operator ordering и profile-specific account state не реконструируются. |
| Unconditional observed-opportunity policy inference | Реализовано 1.26.4 | Economic mean, horizon phases and moving-block LCB use every observed decision hour. A real hour with `NO TRADE` contributes zero; missing market hours are not synthesized. Trade/no-trade cohort counts are explicit and fail-closed validated for candidate and incumbent. This corrects selection-conditioned inference but does not establish profitability. |
| OI/basis/funding/liquidity/context features | Частично реализовано 1.22.0 | Model использует 10 OHLCV-derived + 7 point-in-time context features: OI changes 1h/24h, mark/index basis и delta, latest settled funding/age с interval effective at decision time и turnover/OI liquidity proxy. Exact OI/basis и funding anchor обязательны; same-split ablation и walk-forward non-inferiority входят в gate. Historical local receipt timestamps, funding forecasts, orderbook-depth features, cross-asset context и richer liquidity regimes отсутствуют. |
| PBO, Deflated Sharpe, full experiment ledger | Частично реализовано 1.34.0 | Prospective append-only trial ledger, aligned returns, contiguous CSCV/PBO, HAC-adjusted DSR и horizon-floored moving-block intervals сохранены. Nominal и cost-stress ×1,5/×2 paths используют union реально наблюдавшихся decision-to-horizon окон, cumulative hourly mark-close MTM и deterministic risk-budgeted sizing с aggregate risk/margin caps; timestamps, terminal return и max drawdown сверяются fail-closed. Выбранная конфигурация получает `REJECTED_COST_STRESS`, если любой обязательный stress-path compounds ниже 0%. Genuine `NO TRADE`/holding hours остаются нулями, недоступные календарные разрывы исключаются и раскрываются counts. Новая family требует immutable preregistration; normal activation требует report v4/gate v3, exact artifact/deployment-policy binding и passed cost-stress evidence. Automatic bounded RR/EV family объявляется до trial и не адаптируется к returns. Release 1.33.0 добавляет exact-target operator cancellation; release 1.34.0 запускает formal subprocess в изолированном process tree и завершает POSIX process group либо Windows tree при cancel, timeout, non-zero exit и control failure. Structured tree evidence попадает в append-only `FAILED`, control result и candidate terminal gate; preregistration/предыдущие events не изменяются, candidate activation request закрывается, incumbent сохраняется. Pre-1.18 trials не реконструируются; pre-1.20 families не считаются preregistered; external trusted timestamp, conditional search spaces, arbitrary hyperparameter search, experiments outside ledger и независимая external replication отсутствуют. |
| Production drift monitoring | Частично реализовано 1.28.1; selected-cohort integrity 1.41.0; terminal coverage 1.49.0; all-opportunity telemetry 1.50.0 | Active-version monitor сравнивает production с immutable final-holdout reference: terminal processing coverage, feature/probability PSI, selected-direction log-loss/Brier и actionability density. Release 1.50.0 сохраняет первое успешное artifact evaluation каждого `model_version × symbol × event_time` до spread/funding/EV/RR/publication filters в immutable `model.model_inference_observations`; feature/probability PSI поэтому больше не conditioned on published signals. Published full-horizon mature signals остаются cohort для realized calibration. Schema/version-invalid observations блокируют report fail-closed. Ledger prospective: pre-1.50 rejected opportunities не реконструируются; multivariate tests, adaptive control limits и automated rollback отсутствуют. |
| Fail-closed model activation gate | Реализовано 1.28.0; selected calibration strengthened 1.41.0; actionable calibration strengthened 1.42.0; symbol jackknife strengthened 1.43.0; cluster jackknife strengthened 1.44.0; market-regime robustness strengthened 1.45.0; directional robustness strengthened 1.46.0; interaction robustness strengthened 1.47.0; sparse-pool jackknife strengthened 1.48.0 | Normal activation требует passed model quality gate и experiment promotion gate v3 с passed cost-stress evidence. Release 1.41.0 применяет existing absolute log-loss/Brier limits к выбранному LONG/SHORT-направлению и связывает paired evidence counts. Release 1.42.0 дополнительно вычисляет и проверяет calibration exact post-actionability/post-overlap trade cohort. Release 1.43.0 добавляет exact leave-one-symbol-out recomputation, а 1.44.0 — leave-one-correlation-cluster-out. Release 1.45.0 классифицирует каждую opportunity по ex-ante decision-time regime и отдельно проверяет каждый торгуемый режим. Release 1.46.0 пересчитывает exact actionable economics/calibration отдельно для LONG и SHORT. Release 1.47.0 добавляет exact `symbol × direction × regime` cells: ячейки с ≥5 trades проверяются отдельно, а меньшие объединяются в один sparse-pool. Release 1.48.0 дополнительно удаляет каждую sparse-cell по очереди и требует, чтобы остаток сохранял ≥5 trades, положительный mean R и допустимую calibration; одна удачная tiny-cell не может поддерживать весь pool. Interaction symbol/direction/regime sets должны точно совпадать с marginal evidence. Все schema, counts, fractions, weighted pool/jackknife metrics, summaries и runtime evidence проверяются fail-closed. Selected preregistered trial должен совпасть по version/SHA-256/horizon и deployment-policy binding; изменение production economics/risk policy после evidence блокирует activation. Legacy artifact без current evidence отклоняется fail-closed. Emergency rollback требует явного flag + reason и сохраняет исходные evidence в audit. |
| Deferred background promotion reconciliation | Реализовано 1.33.0 | Trainer повторно проверяет newest inactive background candidate с `activation_requested=true` и persisted passed quality gate. Явная operator family имеет приоритет; иначе при `AUTO_TRAIN_AUTO_EXPERIMENT=true` создаётся deterministic candidate-specific family, immutable preregistration фиксируется до первого trial и bounded configurations выполняются последовательно под advisory lock. Пока family incomplete, новый candidate не обучается. `READY` evidence всё равно обязана совпасть с exact artifact/version/horizon и persisted deployment-policy binding; terminal governance rejection, bounded retry exhaustion или authenticated exact-target operator cancellation транзакционно закрывают activation request с audit/outbox evidence. Отмена/terminal rejection завершает текущий scheduling cycle и не запускает немедленно новый candidate. |
| Operator-visible automatic experiment control | Реализовано 1.34.0 | Fresh trainer heartbeat публикует exact family/candidate, stage, configuration, attempt и `subprocess_active`. `CANCEL_EXPERIMENT` требует exact target и CSRF/authenticated operator context. Formal subprocess запускается в isolated POSIX session/process group или Windows `CREATE_NEW_PROCESS_GROUP`; cancel/timeout/failure завершает всю доступную group/tree и сохраняет `subprocess-tree-termination-v1`. Mismatched/stale requests fail closed; pending `CHECK_NOW`/`RECOVER_NOW` не блокирует cancel; open trial закрывается append-only `FAILED`; preregistration и прошлые results не удаляются. Linux descendant runtime доказан; Windows runtime и намеренно detached POSIX `setsid()` descendants остаются непроверенными/вне group guarantee. |
| Candidate/live recommendation attrition diagnostics | Реализовано prospectively; mature outcome attribution 1.35.0 | Каждый background training attempt, `symbol × event_time` inference opportunity и initial execution plan получает terminal outcome/cause; retries дедуплицируются. Report v3 exact-join связывает instrumented `signal_id`/`plan_id` с persisted `SignalOutcome`/`PlanOutcome`, использует только full-horizon mature cohort с `resolved_at <= report.until` и показывает TP/SL/TIMEOUT, ambiguity, valuation coverage и descriptive `counterfactual_r` по initial status/stage/reason. Missing/conflicting mature evidence блокируется. История до 1.24.0 не реконструируется; это counterfactual diagnostic, не actual execution PnL, causal decomposition или основание ослаблять gates. |



## Work package: symbol × direction × regime interaction robustness

Release 1.48.0 усиливает interaction robustness после 1.47.0 и закрывает single-sparse-cell concentration gap. Release 1.47.0 закрыл masking достаточно поддержанных cells после отдельных проверок symbols, directions и regimes. Положительные marginal averages могли скрывать отрицательную exact cell, например `BTCUSDT × LONG × UPTREND`.

Реализация:

- cells строятся только после direction selection, EV/RR actionability и overlap filtering;
- regime assignment переиспользует тот же development-only decision-time contract, что и release 1.45.0;
- cell с минимум пятью trades получает отдельные realized mean R, log loss и multiclass Brier;
- cells с меньшей поддержкой объединяются в один deterministic sparse-pool, а не игнорируются и не превращаются в множество слабых тестов;
- non-empty sparse-pool обязан иметь минимум пять совокупных trades и проходить те же economics/calibration limits;
- release 1.48.0 для каждой sparse-cell строит exact leave-one-cell-out residual и требует ≥5 остаточных trades, положительный mean R и существующие log-loss/Brier limits;
- validator сверяет canonical cell order, exact omitted identity, residual counts/fractions, calibration rows, weighted sparse-pool/jackknife metrics, extrema и exact symbol/direction/regime sets;
- runtime требует schema `symbol-direction-regime-supported-cells-sparse-pool-jackknife-v2` и nested `leave-one-sparse-interaction-cell-out-v1`; policy metric schema повышена до v25.

Ограничения: пять trades — минимальный safety floor, а не сильная статистическая мощность. Jackknife доказывает только отсутствие зависимости pool от одной cell. Несколько вредных tiny cells всё ещё могут маскироваться несколькими прибыльными cells, если каждый leave-one-out residual остаётся положительным. Partition не является causal or hierarchical model и не доказывает forward profitability.

## Work package: decision-time market-regime robustness

Release 1.45.0 закрывает regime-masking gap. Aggregate actionable mean R и calibration могли оставаться допустимыми, хотя один фактически торгуемый рынок-состояние был отрицательным или статистически недостаточным.

Реализовано:

- regime assignment использует только decision-time `ret_24h` и `atr_pct_14`, уже входящие в feature schema;
- high-volatility threshold рассчитывается как 75-й процентиль market-median ATR percentage только на development window, без final-holdout outcomes;
- вне high-volatility состояния UPTREND/DOWNTREND задаются immutable threshold `|ret_24h / atr_pct_14| >= 1.0`, остальные observations относятся к RANGE;
- exact actionable cohort стратифицируется после direction selection, EV/RR actionability и overlap filtering;
- evidence сохраняет opportunity/trade/no-trade cohorts, trade fraction, realized mean R и exact actionable log-loss/Brier для каждого observed regime;
- normal activation требует минимум пять сделок и прохождение неизменённых economic/calibration limits в каждом режиме, который policy фактически торгует;
- validator и runtime проверяют schema, development threshold, canonical ordering, totals, fractions, summaries и calibration row counts.

Ограничения: это preregistered statistical partition, а не causal macro-regime model. Multi-regime diversification не требуется: стратегия может торговать один режим, но он должен иметь достаточную поддержку и проходить все limits. Forward threshold stability, per-symbol-by-regime cells и causal profitability не доказаны.

## Work package: final-holdout policy correlation-cluster jackknife robustness

Release 1.44.0 закрывает group-concentration gap, который не обнаруживает single-symbol jackknife. Несколько сильно зависимых instruments могли совместно обеспечивать весь положительный результат: удаление любого одного сохраняло другой прибыльный proxy, но удаление всей группы оставляло убыточный universe.

Реализовано:

- корреляция считается по `realized_r` exact post-actionability/post-overlap trades только на timestamps, где оба symbols действительно торговались;
- immutable rule соединяет symbols при абсолютной Pearson correlation не ниже `0.70` и минимум восьми совместных active observations;
- транзитивные connected components образуют детерминированные sorted clusters;
- каждый cluster полностью исключается, оставшиеся simultaneous trades перевзвешиваются, а исходный observed opportunity clock и zero-return no-trade hours сохраняются;
- quality gate требует минимум два clusters и worst leave-one-cluster-out mean R строго выше `AUTO_TRAIN_MIN_POLICY_REALIZED_MEAN_R`;
- validator сверяет schema, threshold, minimum observations, cluster IDs, symbol uniqueness, counts, fractions, extrema и точное совпадение symbol set с per-symbol evidence;
- runtime отклоняет отсутствующее, malformed или legacy evidence fail-closed.

Ограничения: threshold и minimum overlap preregistered как константы текущей schema, но не доказывают экономически истинную sector taxonomy. При недостаточном числе совместных сделок symbols остаются singleton clusters. Проверка использует realized final-holdout returns, не per-symbol calibration, не ex-ante sector taxonomy и не causal profitability. Market-regime stratification добавлена в 1.45.0 отдельным decision-time contract.

## Work package: final-holdout policy symbol jackknife robustness

Release 1.43.0 закрывает cross-symbol concentration gap. До исправления temporal phase bootstrap, walk-forward, actionable calibration и aggregate policy economics могли быть зелёными, хотя один instrument создавал весь положительный результат, а оставшийся traded universe был убыточным.

Реализовано:

- jackknife выполняется после direction selection, EV/RR actionability и single-active-trade-per-symbol overlap filtering;
- для каждого traded symbol удаляются все его сделки, оставшиеся одновременные сделки заново получают равный вес, а все реально наблюдавшиеся no-trade opportunity hours сохраняются нулями;
- evidence содержит exact sorted symbol list, per-symbol trade count/fraction, per-symbol leave-one-out mean, maximum trade fraction и worst leave-one-out mean;
- schema, нормализация/уникальность symbols, суммы counts, fractions и summary extrema проверяются fail-closed;
- normal quality gate требует минимум два traded symbols и `worst leave-one-out mean R > AUTO_TRAIN_MIN_POLICY_REALIZED_MEAN_R`;
- runtime требует current evidence, policy metric schema повышена до v20, legacy artifacts требуют переобучения.

Ограничения: single-symbol jackknife дополнен correlation-cluster jackknife 1.44.0, но всё ещё не проверяет per-symbol calibration, ex-ante sector taxonomy или causal profitability. Market-regime robustness добавлена в 1.45.0. При небольшом числе сделок тест консервативен намеренно.


## Work package: decision-time entry anchoring and publication boundary

Release 1.40.0 закрывает research/live geometry defect: вероятности TP/SL/TIMEOUT относились к close подтверждённой decision candle и следующему часовому open, но live selector ранее центрировал новую entry zone, SL и TP вокруг текущего bid/ask. При delayed catch-up это позволяло использовать старые вероятности для фактически новой сделки после существенного движения цены; signal expiry дополнительно начинался от publication time и продлевал старое решение.

Реализовано:

- immutable decision anchor берётся из exact close подтверждённой source candle;
- historical LONG/SHORT next-hour adverse-spread entry proxies допускаются только внутри `decision_anchor ± ENTRY_ZONE_ATR_FRACTION × ATR`; timestamp pair исключается целиком, если хотя бы одна directional geometry вне зоны;
- live bid и ask обязаны одновременно находиться в той же зоне; selector больше не переносит зону вслед за текущим рынком;
- publication блокируется при lag больше `MAX_SIGNAL_PUBLICATION_DELAY_SECONDS`;
- signal expiry вычисляется как `event_time + SIGNAL_TTL_MINUTES`, а не `publish_time + TTL`;
- entry-zone fraction и publication-delay limit входят в artifact metadata и immutable promotion-policy binding v4; live publication дополнительно требует exact artifact/config match, а legacy artifacts с прежней entry schema отклоняются fail-closed и требуют переобучения;
- stop/TP, fees, spread, funding, EV и net R/R продолжают рассчитываться от фактической executable entry, но только после подтверждения, что рынок остаётся в исходной decision zone.

Ограничения: historical entry всё ещё является next-hour open ± directional half-spread proxy, а не exact bid/ask/VWAP/fill. Нет sub-hour gap ordering, queue/latency model и causal доказательства прибыльности. Новый контракт может уменьшить число actionable observations и рекомендаций, поскольку исключает уже ушедшие цены; это преднамеренный fail-closed эффект.


## Work package: decision-time execution snapshot freshness barrier

Release 1.39.0 закрывает mass-staleness defect, при котором fresh market signals получали profile-specific execution plans со статусом `BLOCKED_STALE_DATA`. Ticker refresh 1.35.5 выполнялся непосредственно перед publication, но account snapshot и orderbook оставались результатом более раннего общего poll. Startup additionally выполнял catch-up inference до первого private account sync, а initial backfill мог состарить order books на часы.

Реализовано:

- hourly и universe-catchup inference используют общий `_refresh_execution_inputs`;
- при `BYBIT_READ_ONLY_ACCOUNT=true` wallet/equity и positions обновляются до market-depth refresh;
- active-universe order books обновляются после account state и до final ticker batch;
- non-empty universe с нулевым stored/duplicate orderbook coverage блокирует transaction до signal write;
- private account refresh failure также блокирует publication;
- partial orderbook coverage сохраняется в `JobRun.details.execution_input_refresh`, а per-symbol age/depth checks остаются fail-closed;
- freshness windows, signal TTL, model/promotion gates, EV/RR и risk limits не изменены.

Отдельный вывод по trainer readiness: `4 из 1206` в dynamic mode является честным prospective count, а не скоростью candle backfill. Point-in-time replay исключает все decision rows до первого committed eligibility snapshot, поскольку historical membership/spread decisions не могут быть восстановлены из OHLCV. Release не фабрикует pre-ledger evidence и не снижает 1206.

Ограничения: live PostgreSQL/Bybit startup не проверен; последовательный REST orderbook refresh полного operator universe не benchmarked. Частичные public API failures по-прежнему могут блокировать отдельные symbols. Исправление operational availability не доказывает прибыльность стратегии.

## Work package: immutable background trainer preflight scope

Release 1.38.0 закрывает расхождение между dataset, который разрешал background training, и dataset, на котором фактически строился candidate. До исправления dynamic preflight применял `AUTO_TRAIN_MAX_SYMBOLS` и сохранял exact `training_data_profile.symbols`, но `run_training_once` игнорировал этот список в dynamic mode, загружал все symbols и заново выбирал latest database horizon.

Исправление:

- background training fail-closed требует валидный persisted trigger profile с symbols и end time;
- static и dynamic modes используют один exact preflight symbol list;
- last/mark/index queries ограничены `preflight.end_time + horizon`, поэтому данные, появившиеся после scheduler decision, не меняют attempt;
- actual candidate profile сравнивается с expected profile; changed symbols, post-feature coverage ниже `AUTO_TRAIN_MIN_SYMBOL_COVERAGE_RATIO` и temporal advance блокируют quality gate;
- expected/actual scope сохраняются в gate evidence.

Ограничения: preflight всё ещё является быстрым candle/replay profile, а не полным dry-run feature/context/label construction. Release fail-closed обнаруживает divergence после candidate construction, но не исключает вычислительно бесполезный fit при неполном OI/mark/index/funding context. Следующий work package — stage-by-stage eligibility audit. Пороговые значения и риск не ослаблены; исправление не доказывает прибыльность.

## Work package: durable PostgreSQL-backed model artifacts

Release 1.36.0 закрывает подтверждённый deployment/state defect: `MODEL_DIR=models` находился внутри release tree, registry сохранял абсолютный путь, а clean ZIP корректно исключал `*.joblib`. После замены/удаления старого каталога PostgreSQL сохранял active version и SHA, но единственные bytes исчезали; runtime переходил на baseline, а trainer мог восстановиться только новым candidate после всех data/quality gates.

Реализовано:

- exact artifact bytes, registry UUID, version, SHA-256 и size сохраняются в одной transaction с candidate registry, audit и outbox;
- PostgreSQL constraints проверяют positive/bounded size и exact payload length, UPDATE/DELETE запрещены trigger;
- local file считается materialized runtime copy, а не единственным durable state;
- worker, trainer и registered activation проверяют/архивируют local file либо восстанавливают missing copy из PostgreSQL до runtime validation;
- restore выполняется через temp file, fsync, post-write hash и atomic replace; повреждённый local file не перезаписывается;
- status API/UI раскрывают наличие DB archive и результат durability check;
- quality, walk-forward, holdout, experiment, EV/RR и risk gates не меняются.

Ограничения: migration не может создать bytes для artifact, который был удалён до 1.36.0 и не сохранился ни в одном release/backup. PostgreSQL integration и реальный service restart в этой среде не выполнялись. Хранилище увеличивает размер DB backups; artifact ограничен 256 MiB. Исправление не доказывает прибыльность и не устраняет отдельно наблюдаемый недостаток point-in-time eligible history.


## Work package: timezone-stable universe snapshot hashing

Release 1.34.2 закрывает подтверждённый operational/temporal-integrity defect в trainer preflight. Immutable `market.universe_eligibility_snapshots` хешировали `observed_at` и `recorded_at` через текстовое `datetime.isoformat()`. PostgreSQL `TIMESTAMPTZ` хранит момент времени, но возвращает его в timezone текущей DB session; один instant мог быть записан как `+00:00`, а прочитан как `+03:00`. Из-за разных JSON bytes validator ошибочно объявлял неизменённую запись повреждённой и блокировал `load_training_data_profile`, `due_reason` и trainer control.

Реализовано:

- top-level snapshot timestamps канонизируются в UTC до persistence hash и replay revalidation;
- policy/record hashes, mode, decision coverage и selected-symbol consistency не ослаблены;
- настоящий mismatch по-прежнему fail-closed блокирует training/backtest;
- error context содержит точные `snapshot id`, `mode` и `recorded_at`;
- regression воспроизводит одинаковые instants в UTC и UTC+03, второй regression проверяет диагностику реально неверного hash.

Ограничения: PostgreSQL integration и Windows PostgreSQL timezone smoke не выполнялись в этой среде. Релиз не переписывает immutable rows, не ослабляет model gates и не гарантирует, что однодневный candidate пройдёт minimum-history/final-holdout требования.


## Work package: policy-actionable calibration integrity

Release 1.42.0 closes a second, narrower selection-bias gap after direction selection. Release 1.41.0 measured calibration of the LONG/SHORT side chosen for each opportunity, but that cohort still included opportunities later rejected by EV/RR/actionability and single-active-trade overlap rules. A deterministic final-holdout reproducer showed that 130 well-classified non-trades could keep aggregate selected-direction log loss below 1.20 while 20 actual policy trades had log loss above 4 and multiclass Brier above 1.5.

The release computes a separate `actionable-policy-trades-final-holdout-v1` calibration from the exact rows remaining after actionability and overlap filtering. The quality gate applies the unchanged absolute calibration limits, requires its row count to equal `policy_trades`, and rejects missing/non-finite/inconsistent evidence. Policy metric schema v19 and runtime validation make this artifact contract immutable; pre-1.42 artifacts require retraining. This does not prove profitability and does not relax trade-rate, holdout, walk-forward, EV/RR, spread or risk gates.

## Work package: policy-selected calibration integrity

Release 1.41.0 closes a confirmed selection-bias gap in activation evidence. The final holdout represents each opportunity by two counterfactual directional rows, while production publishes at most one selected direction. Training already calculated selected-direction log loss and multiclass Brier, but the gate enforced only all-direction averages. Good calibration of the unused side could therefore mask overconfidence in the actual recommendation.

The release now requires an explicit selected-direction calibration mapping, checks it against the unchanged absolute ML limits and binds evidence cardinalities fail-closed: `holdout_rows = 2 × policy_candidates`, `selected_calibration_rows = policy_candidates`, and drift-reference rows equal holdout rows. Drift-reference schema v3 and selected cohort schema v2 make the new semantics immutable; legacy artifacts require retraining. This hardening does not claim profitability and does not relax any ML, policy, spread, EV/RR or risk gate.

## Work package: promotion-bound market-signal funding semantics

Release 1.34.1 закрывает подтверждённый econometric deployment mismatch. Candidate policy metrics и promotion gate явно требуют `policy_expected_funding_source=none-no-point-in-time-forecast` и `funding_rate_override=0`, потому что historical point-in-time funding forecast snapshots отсутствуют. Однако live `publish_hourly_signals` передавал текущий ticker funding projection в `select_cost_aware_scenario`, поэтому после activation иной, не проверенный на final holdout cost overlay мог изменить ranking LONG/SHORT. На симметричных probabilities и нулевых остальных издержках положительный funding менял deterministic selection с LONG на SHORT, хотя OOS policy выбирала LONG.

Реализовано:

- введён единый `POLICY_EXPECTED_FUNDING_SOURCE`; training metrics, lifecycle gate и signal publication используют один контракт;
- `select_cost_aware_scenario` fail-closed отклоняет любой ненулевой expected funding, чтобы новый caller не мог скрытно переопределить promotion-bound market policy;
- live publication сохраняет market-signal funding scenario равным нулю и раскрывает источник в `feature_snapshot.economics_assumptions`;
- текущий ticker funding projection сохраняется отдельно как diagnostic evidence на момент публикации;
- `create_execution_plan` и acceptance по-прежнему независимо пересчитывают свежий projected funding, включают adverse funding в downside/net EV и могут перевести план в `NO_TRADE`/заблокировать acceptance;
- fees, slippage, stop-gap reserve, barrier geometry, risk sizing, model artifact и activation thresholds не ослаблены.

Ограничения: исправление не создаёт historical forecast dataset и не доказывает прибыльность. Market-signal net economics временно не включает ex-ante funding forecast; execution-plan economics включает свежий adverse projection и поэтому может быть строже signal-level evidence. После накопления point-in-time forecast history допустим новый versioned policy contract и повторное governed OOS evidence, но не silent reuse текущих artifacts.


## Work package: automatic-experiment process-tree containment

Release 1.34.0 закрывает подтверждённый operational defect release 1.33.0. Exact-target cancellation завершала direct Python child, но не его descendants. Реальный regression на исходном release создавал sleeping grandchild с отдельными `DEVNULL` streams: после `CANCEL_EXPERIMENT` direct child завершался, а grandchild продолжал жить. Такой процесс мог продолжить CPU/IO и писать research evidence после terminal operator action.

Реализовано:

- subprocess создаётся только с поддерживаемым containment contract: POSIX `start_new_session=True` или Windows `CREATE_NEW_PROCESS_GROUP`; неизвестная OS блокирует запуск;
- POSIX cleanup адресует весь process group через `SIGTERM`, проверяет live non-zombie group members и при необходимости применяет `SIGKILL`;
- Windows contract использует built-in `taskkill /PID <root> /T`, затем `/F`; ненулевой результат обоих вызовов не считается подтверждённой остановкой;
- одинаковый cleanup применяется при authenticated cancel, timeout, non-zero root exit, exception в cancellation/control probe и task cancellation;
- termination result имеет immutable JSON-compatible schema `subprocess-tree-termination-v1` с platform, scope, root/group PID, graceful/force action, verification method и `tree_termination_verified`;
- process-tree evidence передаётся в append-only failed trial, trainer status, control completion и candidate terminal gate;
- regression tests запускают настоящий grandchild и доказывают его отсутствие после cancel, timeout, non-zero root exit и probe failure.

Ограничения: Linux runtime proof относится к descendants, наследующим process group. Процесс, который намеренно вызывает `setsid()`/создаёт отдельную session, может выйти из POSIX group containment. Windows branch проверена unit-контрактом flags/`taskkill`, но реальный Windows smoke не выполнялся. Это operational safety, а не доказательство прибыльности или качества модели.


## Work package: automatic preregistered candidate experiment lifecycle

Release 1.32.0 closes the operational gap between a quality-passed inactive background candidate and the existing experiment-promotion gate. Previously the trainer could only poll an externally prepared family; with an empty `AUTO_TRAIN_EXPERIMENT_FAMILY`, the candidate remained inactive indefinitely and later scheduling iterations could train additional candidates without completing governance for the exact artifact.

Implemented contract:

1. An explicit operator-provided family still has precedence.
2. Otherwise, a deterministic family name is bound to candidate version, artifact SHA-256, immutable governance defaults and the complete bounded RR/EV plan.
3. `scripts.backtest --prepare-preregistration` derives the exact final-test cohort and fixed configuration without starting a trial.
4. Every placeholder is replaced, the full search space and stopping rule are fixed, and registration commits before the first `STARTED` event.
5. Configurations run sequentially; observed returns cannot add, delete or reorder grid values.
6. The exact deployment thresholds must be one preregistered configuration, and activation remains impossible unless that exact policy is selected and every existing quality/PBO/DSR/dependence/cost-stress gate passes.
7. Successful trials are idempotently skipped, failed trials have a bounded retry budget, subprocess aborts close any open ledger attempt append-only, and stale open attempts are recovered after the configured timeout.
8. Pending governance suppresses creation of another candidate; terminal rejection closes only the inactive candidate request and never deactivates the incumbent.

The implementation is not generic AutoML, nested hyperparameter optimization or evidence of profitability. It explores only the declared RR/EV threshold grid and deliberately rejects adaptive search based on observed trial returns.


## Work package: PostgreSQL-native as-of universe replay loading

Release 1.31.0 устраняет масштабируемый, но семантически скрытый дефект реализации replay. Версия 1.30.0 запрашивала все пятиминутные `UniverseEligibilitySnapshot` в lookback-окне и материализовала их ORM-объекты вместе с крупными JSON `policy` и `decisions`, хотя research dataset принимает решения почасово и для каждого timestamp использует только один latest-prior snapshot. При годовом lookback это создавало примерно двенадцатикратное избыточное число snapshot rows до учёта размера JSON evidence.

Реализовано:

- `app/ml/universe_replay.py::load_point_in_time_universe_snapshots` передаёт PostgreSQL unique UTC decision timestamps одним `TIMESTAMPTZ[]`;
- correlated `LEFT JOIN LATERAL` выбирает commit availability `recorded_at <= decision_time`, а не observation-time range;
- query возвращает первый rollout snapshot и только distinct `recorded_at`, реально требуемые hourly decisions; все строки с одинаковым выбранным `recorded_at` сохраняются, чтобы ambiguity по-прежнему блокировалась fail-closed;
- full immutable rows читаются через streaming result с bounded fetch batch, затем повторно проверяются schema, policy hash, record hash и selected-symbol consistency;
- после проверки retained DataFrame содержит только `observed_at`, `recorded_at`, `selected_symbols`, `policy_hash` и `record_hash`; bulky `policy`/`decisions` не накапливаются в process memory;
- migration `0016_universe_replay_asof` добавляет индекс `(mode, recorded_at)`, используемый latest-prior lookup;
- replay evidence раскрывает loader schema, число requested decision timestamps и число streamed/retained snapshots.

Структурная граница результата без duplicate availability: не более `N + 1` snapshot rows для `N` unique decision timestamps вместо всех пятиминутных rows lookback. Actual PostgreSQL `EXPLAIN ANALYZE`, latency и RSS на production-size ledger не измерены из-за отсутствия отдельной PostgreSQL среды; integration test для reduced result и index plan добавлен, но в этой итерации пропущен. Изменение не меняет membership semantics, thresholds или доказательность прибыли.


## Work package: fail-closed point-in-time universe replay

Release 1.30.0 соединяет prospective eligibility ledger 1.29.0 с model training, background preflight и formal backtest. До исправления наличие ledger не влияло на research dataset: labels по-прежнему строились из candle-coverage cohort, поэтому instrument мог попасть в train/holdout даже когда production filters исключали его по turnover, spread, age, status или rank limit.

Реализовано:

- `app/ml/universe_replay.py` выполняет deterministic as-of join по **commit availability** `recorded_at <= decision_time`, а не по времени наблюдения;
- для каждого decision timestamp используется ровно один latest committed snapshot; duplicate availability, invalid hashes/timestamps/symbol arrays и contradictory persisted evidence блокируются;
- rows до первого committed prospective snapshot исключаются и раскрываются отдельно, без фиктивной реконструкции;
- после rollout любой snapshot старше `2 × UNIVERSE_REFRESH_SECONDS` блокирует весь run, а не создаёт silent fallback;
- dataset сохраняет только symbols из `selected_symbols` соответствующего snapshot; LONG/SHORT pair остаётся атомарной, потому что фильтрация выполняется по `symbol × decision_time`;
- dynamic loader загружает все symbols в bounded lookback перед replay, поэтому current coverage ranking не может заранее выбросить исторически выбранный instrument;
- background `training_data_profile` использует тот же replay и честно ждёт minimum prospective timestamps;
- candidate artifact, quality metrics, backtest report и preregistered trial configuration сохраняют schema, bounds, row attrition, snapshot age, policy hashes и exact record hashes.

Ограничения: evidence до migration/первого successful 1.29.0 refresh отсутствует и не восстанавливается. Snapshot cadence остаётся worker-observed REST evidence, а не exchange-native historical universe feed. Replay не реконструирует historical orderbook, min order, latency, operator action или delisted instruments до local observation. Он устраняет selection look-ahead и cohort mismatch, но не доказывает прибыльность и не увеличивает частоту рекомендаций.


## Work package: prospective universe eligibility ledger

Release 1.29.0 создаёт воспроизводимый point-in-time источник для будущей exact production-universe reconstruction. До исправления dynamic universe вычислялся из текущих instrument/ticker responses, сохранялся только в памяти worker и попадал лишь в агрегированный `JobRun.details`; при этом detailed ticker snapshots удалялись retention job. После нескольких часов нельзя было доказать, какой конкретно инструмент был eligible, исключён или отсечён лимитом и на основании каких observed значений.

Реализовано:

- каждый static/dynamic refresh формирует полный decision set по всем рассматриваемым instrument rows, включая `eligible_before_limit`, final `selected`, deterministic rank и stable reason code;
- evidence содержит instrument category/status/launch time/age/pre-listing/contract/symbol type и observed ticker last/bid/ask/turnover/spread;
- exact selection policy нормализуется, хешируется SHA-256 и сохраняется вместе с selected symbols и coverage counts;
- migration `0015_universe_eligibility` добавляет `market.universe_eligibility_snapshots`; record hash, JSON shape/count constraints и PostgreSQL trigger делают snapshot append-only;
- snapshot, ticker/orderbook writes, initial backfill и `market_sync` terminal status находятся в одной PostgreSQL transaction;
- worker обновляет `active_symbols`, summary и refresh timestamp только после successful commit, а не во время незавершённой transaction;
- restart в ту же scheduled minute может восстановить committed universe из previous successful `market_sync` details.

Ограничения: ledger начинает накапливаться только после migration/upgrade; exchange server timestamp для all-tickers response недоступен в текущем client contract, поэтому `observed_at` является UTC временем получения/решения worker. Static mode сохраняет configuration decision, но не пытается выдать рыночные поля за eligibility inputs. Начиная с 1.30.0 training/backtest потребляют ledger через fail-closed point-in-time replay. До первого prospective snapshot история остаётся intentionally unavailable.


## Work package: point-in-time training universe integrity

Release 1.28.2 закрывает econometric и operational mismatch в dynamic trainer. До исправления `_select_training_symbols` ранжировал symbols по самому свежему `TickerSnapshot.turnover_24h`, а затем использовал этот современный список для исторического lookback. Latest turnover находился позже label cutoff для части выборки, недавно разогретые контракты могли не иметь minimum history, а повторное разрешение universe перед fit могло отличаться от preflight `training_data_profile`.

Реализовано:

- capped dynamic cohort строится только из confirmed hourly last-price candles;
- selection window ограничен configured lookback и заканчивается на `latest confirmed candle - horizon`;
- symbol должен иметь не меньше configured minimum bars и достигать label cutoff;
- ordering детерминирован: eligible row count, latest eligible candle, symbol;
- latest ticker turnover полностью исключён из historical training selection;
- explicit empty cohort остаётся empty/fail-closed, а `None` отдельно означает unrestricted mode;
- background trainer переносит exact symbols из trigger profile в data load и fit;
- manual trainer передаёт horizon/minimum-history contract в тот же loader.

Ограничения: release не реконструирует membership до начала prospective ledger. Начиная с 1.37.0 historical dynamic replay использует сохранённый snapshot spread и точный `MAX_SPREAD_BPS`, но это top-of-book observation, а не historical depth/fill proof. Static-mode historical spread cohort и operator latency остаются нереконструируемыми. Default quality gates не ослаблены: 24 часа данных недостаточно против requirement 1206 unique hourly timestamps.


## Work package: critical drift evidence precedence

Release 1.28.1 закрывает fail-open конфликт статусов внутри production drift report. До исправления `BLOCKED` имел более высокий внутренний приоритет, чем `CRITICAL`. Поэтому independently confirmed critical PSI, missingness, probability, calibration или actionability evidence могла быть перезаписана низким coverage, неполным warm-up, failed inference job или incomplete mature outcomes. Publication guard сохранял quarantine только для persisted overall status `CRITICAL`, и такой report не включал interlock.

Реализовано:

- report schema последовательно повышена до `production-drift-report-v4`;
- evidence разделена на `critical_evidence`, `blocking_evidence` и `warning_evidence`;
- общий статус вычисляется независимо от порядка проверок: CRITICAL при любой валидной independent critical evidence, затем BLOCKED, WARN и OK;
- release 1.49.0 использует `symbol_outcome_count` как authoritative processed denominator: intentional `SKIPPED`/`NO TRADE` terminal outcomes считаются завершённой обработкой, но не actionable рекомендациями;
- coverage считается как `processed terminal outcomes / expected symbol opportunities`, actionability density — как `published-or-existing actionable signals / expected symbol opportunities`;
- reference actionability rate использует final `policy_trades / policy_candidates` и cohort schema `published-policy-trades-per-symbol-opportunity-v1`, а не pre-overlap actionable candidates;
- failed inference jobs, missing/malformed terminal coverage и incomplete maturity добавляют blockers, но не подавляют independently valid feature/probability/actionability critical evidence;
- incomplete/invalid maturity удаляет calibration-only critical/warning evidence и переводит calibration section в `BLOCKED`;
- missingness становится critical только при наличии configured minimum denominator; empty warm-up остаётся blocked;
- существующий exact-version persisted quarantine автоматически применяется к v4 reports со статусом `CRITICAL`; старые persisted critical reports продолжают учитываться guard.

Ограничения: feature/probability PSI по-прежнему использует stored published signals, потому что отдельный bounded immutable telemetry ledger всех evaluated symbol opportunities пока отсутствует. Monitor не реализует symbol/regime-conditional drift, multivariate tests, adaptive thresholds, automatic rollback или causal attribution losses. Correct terminal coverage и actionability denominator предотвращают ложный retry/coverage/quarantine, но не доказывают положительный edge.


## Work package: risk-budgeted experiment portfolio accounting

Release 1.28.0 закрывает econometric mismatch между formal experiment-selection path и production execution sizing. До исправления `policy_backtest` делил каждый horizon sleeve поровну по номиналу между одновременными сделками. Production, напротив, вычисляет notional как `risk_budget / stress_downside_rate`, удерживает абсолютный open-risk reserve до выхода и блокирует/ограничивает новые планы общим риск- и margin-cap. Поэтому одинаковый набор сделок мог иметь другое распределение веса, drawdown, Sharpe, DSR/PBO и даже противоположный знак terminal return.

Реализовано:

- deterministic equal-risk allocation внутри simultaneous decision cohort без выдуманного operator ordering;
- open-risk reserve сохраняется от decision до modeled exit и освобождается перед new entries на той же границе;
- cohort пропорционально масштабируется к оставшемуся `MAX_TOTAL_OPEN_RISK_RATE`;
- дополнительный cap использует `research_leverage` и `MARGIN_RESERVE_RATE`;
- nominal, stop-reserve и обязательные ×1,5/×2 cost-stress paths используют одну sizing semantics;
- evidence раскрывает allocated/risk-limited/margin-limited/blocked counts, maximum reserved-risk rate и margin utilization;
- promotion binding v2 включает `risk_rate`, `max_total_open_risk_rate` и `margin_reserve_rate`; изменение любого параметра инвалидирует старое experiment evidence;
- return-path schema повышена до `observed-opportunity-covered-risk-budgeted-hourly-mark-to-market-capital-return-path-v4`, cost-stress до `risk-budgeted-hourly-mark-to-market-cost-stress-v2`.

Ограничения: research replay не знает исторические minQty/minNotional, exact orderbook depth, partial fills, profile-specific account capital, instrument caps или фактический порядок ручного принятия одновременных рекомендаций. При отсутствии ordering cohort масштабируется пропорционально; это честная детерминированная аппроксимация, а не симуляция реального OMS. Исправление не повышает частоту сигналов и не доказывает прибыльность.


## Work package: cost-stress experiment promotion gate

Release 1.26.7 закрывает разрыв между диагностическим cost stress и normal model promotion. До исправления `policy_backtest` публиковал только terminal totals `stress_net_return_cost_x1_5`/`x2`; append-only experiment event и governance report их не требовали. Поэтому family могла получить `READY`, даже когда выбранная политика становилась убыточной при обязательном повышении fees/slippage/adverse funding/stop-gap reserve.

Реализовано:

- для ×1,5 и ×2 формируются полные cumulative hourly MTM capital paths на тех же timestamps, что и nominal evidence;
- entry costs признаются в decision time, отрицательный funding и terminal fees/reserve масштабируются по прежней stress-семантике;
- `SUCCEEDED` event требует schema `hourly-mark-to-market-cost-stress-v1`, два сценария, exact timestamp alignment и reconciliation terminal return/max drawdown;
- выбранный nominal Sharpe trial дополнительно обязан иметь terminal compounded return ≥0 в обоих сценариях, иначе report получает `REJECTED_COST_STRESS`;
- report schema повышена до `experiment-selection-preregistered-governance-v4`, persisted promotion gate — до `model-promotion-experiment-governance-v3`; legacy gate v2 не может авторизовать normal activation.

Ограничения: stress multipliers не моделируют нелинейный market impact, queue position, partial fills, latency или regime-dependent fee tiers. Нулевая граница — минимальная fail-closed проверка знака, а не доказательство достаточной доходности. Частота сигналов не увеличена и gates не ослаблены; для её диагностики нужны prospective attrition reports и реальные forward outcomes.


## Work package: hourly mark-to-market experiment return path

Release 1.26.6 устраняет exit-only recognition в experiment-selection evidence. До исправления весь trade P&L признавался только в modeled `exit_time`: существенная внутрисделочная просадка, восстановившаяся до выхода, давала нулевой interim drawdown и изменяла Sharpe/DSR/PBO/dependence statistics без изменения terminal return.

Реализовано:

- label builder сохраняет cumulative directional gross return по каждому часовому mark close от decision до effective barrier/timeout/liquidation exit;
- historical funding сохраняется как trader-signed cumulative settlement path;
- schema, complete hourly coverage, chronology, finiteness и terminal reconciliation проверяются fail-closed;
- backtest признаёт entry fee и conservative slippage в decision time, funding по observed path, а exit fee и terminal outcome — в effective exit;
- horizon-sleeve capital accounting агрегирует incremental MTM PnL по каждому covered hour и точно сверяется с terminal sleeve capital;
- experiment return schema повышена до `observed-opportunity-covered-hourly-mark-to-market-capital-return-path-v3`; predecessor v2 evidence требует rerun.

Ограничения: hourly close path не восстанавливает sub-hour ordering, exact historical bid/ask/depth, queue position, operator latency, historical risk-tier/MMR changes, cross/portfolio margin, ADL или exchange-accurate liquidation fill. Policy-quality `R` path вне experiment-selection слоя по-прежнему использует отдельную existing outcome/cohort methodology; прибыльность и достаточная частота сигналов не доказаны.

## Work package: observed experiment-period support

Release 1.26.5 устраняет synthetic-zero contamination в experiment-selection evidence. До исправления backtest создавал непрерывный hourly `date_range` от первой decision cohort до последнего exit. Если final holdout содержал два валидных сегмента с разрывом, отсутствующие market/data hours попадали в `period_returns` как нулевые доходности. Эти строки могли увеличить `minimum_periods`, уменьшить дисперсию и изменить Sharpe/DSR/PBO/dependence evidence без наблюдаемого рынка.

Реализовано:

- experiment period grid строится как union каждого реально наблюдавшегося `decision_time` и его полного configured label horizon;
- observed `NO TRADE` и holding periods внутри валидных окон остаются нулевыми return rows;
- календарные часы, не покрытые ни одной decision/label path, не синтезируются;
- evidence раскрывает `observed_opportunity_period_count`, `covered_period_count` и `omitted_unobserved_calendar_period_count`;
- ledger валидирует schema, counts, chronology, uniqueness и calendar-span arithmetic до PBO/DSR;
- `hourly-realized-capital-return-path-v1` не допускается к normal promotion; validation error превращается в диагностический fail-closed gate.

Ограничение release 1.26.5: PnL признавался только в modeled exit timestamps. Это ограничение закрыто release 1.26.6 для experiment-selection capital path. Exact historical orderbook, operator latency и forward profitability evidence по-прежнему отсутствуют.


## Work package: observed-opportunity policy return path

Release 1.26.4 исправляет selection-conditioning в `evaluate_policy_model`. До исправления hourly cohorts создавались только из фактически выбранных сделок. Реальные final-holdout часы, в которые policy решила `NO TRADE`, исчезали из mean return и uncertainty path. Поэтому редкая policy оценивалась условно на собственном отборе, а покрытие horizon phases зависело от появления сделок.

Реализовано:

- полный индекс строится из фактически наблюдавшихся `selected.decision_time`; отсутствующие рыночные часы не синтезируются;
- trade cohort returns reindex на observed opportunity path, а `NO TRADE` получает известную strategy return 0;
- `policy_realized_mean_r`, expected mean, phase means и bootstrap LCB используют один unconditional path;
- отдельно публикуются `policy_trade_cohorts`, `policy_no_trade_cohorts` и opportunity win rate;
- quality gate проверяет арифметическую согласованность candidate и incumbent counts;
- legacy metric/uncertainty schemas отклоняются fail-closed.

Ограничения: исправление не оптимизирует thresholds, не повышает искусственно частоту рекомендаций и не доказывает положительный edge. Оно делает evidence для редкой policy более консервативной и сопоставимой с фактическим hourly decision process. Exact historical orderbook, funding forecasts и полная exchange liquidation mechanics остаются частичными пунктами спецификации.


## Work package: experiment-to-deployment policy binding

Release 1.26.3 закрывает econometric research-to-production mismatch в promotion boundary. До исправления selected trial проверялся только по model version, artifact SHA-256 и horizon. При этом preregistered search space мог выбрать другую policy-конфигурацию — например, меньший slippage, нулевой stop-gap reserve или более мягкий `minimum_net_ev_r` — а activation меняла только active artifact. Production продолжала использовать текущие `.env` thresholds/costs, то есть `READY` evidence относилась к другой торговой стратегии.

Реализовано:

- immutable schema `model-promotion-policy-binding-v1` сохраняется в candidate metrics при обучении;
- binding v3 включает entry-spread label stress, точный live `maximum_executable_spread_bps`, research leverage/liquidation reserve, round-trip fees, slippage, stop-gap reserve, funding/timeout overrides, `minimum_net_rr`, `minimum_net_ev_r`, policy source и portfolio accounting;
- promotion gate schema повышена до `model-promotion-experiment-governance-v3`;
- selected `STARTED.configuration` сравнивается с binding key-by-key; отсутствующий или отличающийся параметр даёт явный `selected_trial_policy_mismatch:<key>`;
- manual fresh activation, deferred trainer activation и registry CLI используют один и тот же persisted binding;
- перед state change persisted binding повторно сравнивается с current deployment settings, поэтому изменение policy после backtest инвалидирует evidence;
- legacy inactive candidate без binding fail-closed и требует нового обучения для normal activation;
- already active artifact не деактивируется, emergency rollback остаётся explicit/reasoned/audited.

Ограничения: это точное связывание реализованных research/production policy parameters, а не доказательство прибыльности. Historical point-in-time funding forecast snapshots по-прежнему отсутствуют; стандартный experiment binding требует нулевой дополнительный funding stress override и artifact-based conditional TIMEOUT model. Изменение binding требует нового governed experiment evidence.


## Work package: deferred governed background promotion

Release 1.26.2 закрывает lifecycle-разрыв после регистрации immutable candidate. До этого trainer проверял experiment family только внутри того же вызова, который только что создал новый artifact. Поскольку exact preregistration/backtests требуют уже известных version и SHA-256, обычный результат был `inactive`; следующие scheduling iterations к candidate не возвращались.

Реализовано:

- поиск newest inactive background candidate с `activation_requested=true`;
- повторная независимая валидация persisted quality gate;
- выбор `AUTO_TRAIN_EXPERIMENT_FAMILY` после регистрации artifact;
- exact version/SHA-256/horizon recheck до activation и повторный recheck family под PostgreSQL lock;
- общий production activation service для trainer и CLI;
- active-version compare-and-swap, artifact runtime validation, audit и outbox в одной транзакции;
- успешная promotion завершает текущую scheduling iteration без немедленного повторного fit;
- missing, non-READY, malformed или mismatched evidence остаётся fail-closed.

Ограничения: trainer не создаёт preregistration и не запускает backtests/experiment family автоматически; `READY` не доказывает live profitability. При нескольких inactive candidates автоматически рассматривается newest quality-passed background candidate; более старую версию можно активировать только явным reviewed CLI workflow.


## Work package: policy-evaluation metadata split integrity

Release 1.26.1 исправляет regression в `_dataset_split_from_frames`: функция сохраняла только базовые label-поля и удаляла complete historical-funding/intrahorizon-margin evidence до `evaluate_policy_model`. В результате production training падал на обязательном margin contract, а historical funding при более мягком режиме мог быть ошибочно интерпретирован как отсутствующий.

Реализовано:

- единый explicit allowlist policy-path metadata;
- сохранение полей во всех train/cal/test и walk-forward windows;
- fail-closed проверка неодинакового набора колонок между окнами;
- неизменный `MODEL_FEATURE_NAMES`, поэтому realized path не становится ML feature;
- regression test через реальный `chronological_split`, а не ручной `DatasetSplit`.

Ограничения intrahorizon proxy, funding forecast и historical exchange reconstruction не изменились.


## Work package: experiment-bound model promotion

Release 1.26.0 закрывает разрыв между prospective experiment-overfitting governance и изменением active model:

- normal activation требует `experiment-selection-preregistered-governance-v4` со статусом `READY`;
- выбранный trial загружается из append-only ledger, его STARTED event и hash chain проверяются;
- selected configuration/preregistration hashes должны совпасть с report;
- configuration обязана ссылаться на exact `model_version`, artifact SHA-256 и horizon;
- central atomic activation function повторно сверяет gate с фактическими artifact bytes до runtime load и PostgreSQL mutation;
- `model-registry activate` пересчитывает family report внутри PostgreSQL transaction и не доверяет внешнему JSON;
- background/manual fresh candidate сохраняется inactive, если exact family evidence ещё не готова;
- attrition report v2 различает model quality failure и experiment-promotion failure;
- emergency rollback остаётся явным, reasoned и audited, но не отключает artifact/concurrency checks.

Ограничения: система не запускает полный experiment family автоматически после training, не создаёт trusted external timestamp, не обнаруживает эксперименты вне ledger и не превращает `READY` в доказательство live profitability. Начиная с 1.26.2 background workflow остаётся двухэтапным, но после immutable candidate → preregistered backtests trainer может завершить exact-artifact activation на следующей scheduling iteration; reviewed CLI activation сохраняется.


## Work package: fail-closed model activation gate

Release 1.25.0 закрывает silent bypass между вычислением model quality gate и state-changing activation:

- центральная atomic activation function требует persisted `passed=true` и пустой список причин до artifact/DB mutation;
- `train --activate` вычисляет обычный gate и при отказе сохраняет inactive candidate с `activation_requested=true`;
- `model-registry activate` проверяет gate, сохранённый в registry metrics;
- missing, failed и contradictory gate evidence fail closed;
- emergency rollback без passed gate сохраняется, но требует явных `--emergency-gate-override` и `--override-reason`;
- audit payload раскрывает исходный gate, override flag и reason; checksum/horizon/concurrency validation остаётся обязательной.

Ограничения: release 1.26.0 связывает normal promotion с exact-artifact experiment-family evidence, но не запрещает осознанный emergency override и не доказывает экономический edge. Override является операторским аварийным действием, а не способом исправить редкие рекомендации.


## Work package: candidate/live recommendation attrition diagnostics

Release 1.24.0 добавляет prospective audit trail для ответа на вопрос, где именно теряются candidate и live opportunities:

- каждый selected symbol в hourly/catch-up job получает один terminal outcome с `event_time` и stable reason code;
- повторные попытки дедуплицируются по `symbol × event_time`, а восстановление после первоначального skip считается отдельно;
- каждый initial execution plan сохраняет schema, terminal stage, primary/contributing reason codes и limiting cap;
- background trainer attempts агрегируются как training failed, quality-gate failed, activated или activation skipped;
- quality-gate reasons группируются по model quality, temporal validation, policy economics, incumbent-relative и evidence integrity;
- exact denominators, duplicate/conflicting records и gate/activation consistency проверяются fail-closed;
- CLI и daily report публикуют единый `candidate-live-attrition-report-v3` с отдельными experiment-promotion causes;
- release 1.35.0 загружает только exact entity IDs из instrumented jobs и связывает их с persisted `MarketSignal`, `SignalOutcome` и `PlanOutcome`;
- outcome comparison использует только cohort с `event_time + horizon_hours <= report.until`, поэтому ранний TP/SL не создаёт right-censoring bias;
- point-in-time availability требует timezone-aware `resolved_at <= report.until`; более поздние rows исключаются и считаются отдельно, а не протекают в исторический отчёт;
- TP/SL/TIMEOUT и ambiguous outcome counts агрегируются по initial plan status, terminal stage и primary reason;
- только `VALUED` sized plans входят в descriptive `counterfactual_r`; `NOT_SIZED`/funding/path/invalid outcomes раскрываются отдельно без фиктивного R;
- missing mature signal/plan outcome, label mismatch, invalid valuation/R pair или duplicate evidence блокируют report;
- `actual_execution_pnl=false` и `causal_claim=false` являются явной частью schema.

Ограничения: evidence накапливается только после upgrade 1.24.0; report не является causal Shapley/decomposition model, не восстанавливает фактические ручные fills и не меняет thresholds, active artifact или risk policy. `counterfactual_r` profile/plan-level и доступен только для sized plans; multi-label contributing reasons нельзя суммировать как независимые потери. Confidence intervals и dependence-aware comparison между reason groups остаются отдельным work package после накопления достаточной forward history.

## Work package: critical production-drift publication interlock

Release 1.27.0 закрывает fail-open разрыв между диагностикой drift и advisory publication. До исправления `CRITICAL` менял только heartbeat, а hourly loop сначала выполнял inference и лишь затем строил drift report. Поэтому уже признанная деградация active artifact не запрещала новые recommendations, пересчёт plans или acceptance ранее actionable plan.

Реализовано:

- guard schema `production-drift-critical-quarantine-v1` восстанавливает latch из успешных `production_drift_monitor` JobRun после activation exact active version;
- любой persisted `CRITICAL` для этой version сохраняет блокировку даже при более позднем `BLOCKED`; report другой version не влияет на текущую;
- hourly order изменён на market close → mature outcomes → drift → inference → retention;
- signal publication short-circuit выполняется до market/profile queries и сохраняет `critical_production_drift` attrition на каждый symbol;
- central execution-plan construction переводит новый/recalculated plan в `NO_TRADE` и сохраняет guard evidence в sizing snapshot;
- acceptance повторно проверяет guard, supersedes старый plan и возвращает `PLAN_RECALCULATION_REQUIRED`;
- exact runtime/signal version сверяется с current active model registry; stale-version mismatch fail-closed;
- release condition — activation другой governed model version; same-version reactivation, disabling new monitor jobs, silent clear и удаление safety evidence не снимают persisted latch.

`BLOCKED` из-за minimum observations, incomplete calibration cohort или иной недостаточности evidence продолжает ухудшать heartbeat, но не latch publication. Это намеренная граница: monitor использует prospective prediction snapshots опубликованных signals, поэтому блокировка до накопления minimum observations создала бы permanent bootstrap deadlock. Такое решение не превращает invalid/critical evidence в pass и не ослабляет quality/promotion gates.

Ограничения: release не реализует multivariate drift tests, adaptive thresholds, automatic rollback, candidate selection или доказательство прибыльности. Карантин действует на exact model version, а не на отдельный symbol/feature; ручной operator должен активировать другую уже прошедшую governance version.

## Work package: maturity-aware delayed-label drift calibration

Release 1.23.0 устраняет right-censoring production calibration: TP/SL может разрешиться до конца horizon, тогда как TIMEOUT появляется только после полного окна. Реализовано:

- feature/probability PSI и actionability сохраняют полный active-version monitoring window;
- calibration cohort включает только сигналы с `event_time + horizon_hours <= generated_at`;
- early resolved outcomes незрелых сигналов исключаются и отдельно считаются;
- каждый mature signal обязан иметь один outcome, иначе report/calibration получают `BLOCKED`;
- report schema, начиная с release 1.28.1 `production-drift-report-v3`, раскрывает `full-horizon-mature-signal-outcomes-v1` coverage и разделённые evidence severities;
- invalid maturity metadata и duplicate outcome evidence блокируются fail-closed;
- active model, artifact contract, thresholds, training и execution semantics не изменены.

Ограничения: это deterministic maturity filtering, а не survival model или inverse-probability-of-censoring weighting. Monitor не реализует multivariate drift tests, adaptive control limits, automated rollback или автоматическое изменение policy.

## Work package: point-in-time funding interval replay

Release 1.22.0 устраняет применение последнего известного `funding_interval_minutes` ко всей исторической выборке. Реализовано:

- нормализованный `FundingIntervalSchedule` по `InstrumentSpecHistory.valid_from` с явным schema `instrument-spec-point-in-time-v1`;
- replay actual settlements и `funding_age_fraction` используют interval, effective в соответствующий event/decision time;
- на стабильных участках cadence проверяется точно; при наблюдаемой смене interval переход валидируется консервативно, а последующие пропуски снова блокируются fail-closed;
- trainer, manual train и backtest получают всю историю interval, а не только latest mapping;
- promotion gate и runtime требуют point-in-time interval metadata;
- feature/context/funding/policy schemas повышены, поэтому legacy artifacts отклоняются и должны быть переобучены;
- backward use earliest observed interval до первой локальной spec-записи раскрывается в metadata, а не маскируется как подтверждённая история.

Ограничения: `InstrumentSpecHistory` накапливается проспективно при instrument sync; release не реконструирует интервалы до первой локально наблюдаемой записи и не добавляет historical funding forecast. Переходная cadence проверяется по наблюдаемым settlement events, а не по недоступному архиву расписаний биржи.

## Work package: prospective recommendation UI exposure ledger

Release 1.21.0 устраняет предположение, что каждый созданный execution plan был доступен оператору. Реализовано:

- first-party browser evidence после ≥50% видимости recommendation tile в активной вкладке в течение ≥1 секунды;
- authenticated/CSRF-protected batch endpoint и идемпотентность по `plan_id` и `client_event_id`;
- server-side проверка plan/version, predecision opportunity, времени события, viewport ratio и dwell;
- append-only `advisory.selection_exposure_ledger` с canonical SHA-256 и PostgreSQL запретом UPDATE/DELETE;
- selection denominator только по verified exposed opportunities; exposure time используется как observation time;
- явные created/exposed/unexposed, coverage, legacy и decision-without-exposure diagnostics;
- `LOW_EXPOSURE_COVERAGE` и integrity errors блокируют corrected IPSW estimate;
- rollout boundary: unexposed pre-1.21 opportunities исключаются из coverage denominator, но legacy plan может войти после реального показа новым UI.

Ограничения: событие не является eye tracking и не доказывает внимание/понимание; exposure через API/CLI/уведомления не фиксируется; browser delivery может потеряться до retry; hidden operator state и bootstrap refit propensity отсутствуют. Exposure evidence не меняет plan status, model, risk или active artifact.

## Work package: formal experiment-family preregistration

Release 1.20.0 закрывает возможность создавать executable trial family только строковым именем после просмотра результатов. Для новых families обязательны:

- preregistration до первого `STARTED`;
- exact dataset fingerprint и horizon;
- полный partition всех backtest configuration keys на fixed и enumerated search parameters;
- primary metric `nonannualized_sharpe`, direction `maximize`;
- immutable PBO/DSR/dependence thresholds;
- maximum unique configuration budget и optional UTC deadline;
- substantive hypothesis и objective exclusion criteria;
- SHA-256 record integrity и PostgreSQL запрет UPDATE/DELETE.

`backtest --prepare-preregistration` формирует draft после построения exact cohort, но возвращается до model evaluation и trial event. `experiment-report` блокирует unregistered legacy family и threshold override. Ограничения: нет external trusted timestamp, conditional parameter spaces, automated failure-to-exclusion classification или automatic promotion gate.


## Work package: current-entry conditional TIMEOUT economics

Release 1.35.1 closes a mismatch between the trained conditional TIMEOUT target and execution repricing. The model target is direction-signed gross TIMEOUT return divided by contemporaneous gross stop distance. Signal publication already converted this `R` value to its signal-reference absolute rate, but execution-plan creation and acceptance previously reused that absolute percentage after current ask/bid or depth VWAP changed.

Implemented:

- immutable `timeout_return_r` is read from the signal evidence;
- current executable entry is validated against directional stop/TP geometry;
- `R` is reprojected onto current gross stop distance and bounded to current `[-1R, TP-support]`;
- plan construction uses converged ask/bid/depth VWAP;
- acceptance uses the fresh executable price;
- legacy signals without conditional `R` keep their stored absolute TIMEOUT rate or configured fallback;
- non-finite `R`, invalid geometry and non-positive stop distance fail closed;
- plan evidence schema is `tp-sl-timeout-current-entry-r-v2`.

Independent regression evidence demonstrates a stale-rate false pass: 0.0526R under the old calculation versus 0.0235R under current-entry semantics for a 0.05R gate. No threshold, probability, risk budget, model artifact or activation gate was loosened.

Limitations: this is a correctness fix, not proof of edge. Existing immutable plans are not rewritten; PostgreSQL integration and real forward execution evidence were not available in the sandbox.

## Work package: latest-prior point-in-time ticker selection

Release 1.35.2 closes a live availability defect in ticker lookup. Signal publication, execution-plan construction and recommendation API/acceptance previously ordered all rows by descending `source_time` and then selected one row. A row timestamped after the current decision/request time therefore became the absolute latest row, failed the subsequent future-time freshness check and masked an older snapshot that was both available and still fresh.

Implemented:

- a shared `latest_available_ticker_query` contract;
- mandatory timezone-aware cutoff;
- `source_time <= cutoff` and `received_at <= cutoff` predicates before ordering;
- deterministic ordering by `source_time DESC`, `received_at DESC`, `id DESC`;
- exact cutoff propagation from hourly signal publication, execution-plan creation, recommendation list/detail and acceptance;
- existing stale-age validation remains unchanged after selection;
- red → green regression coverage for all three former duplicate loaders.

This change does not manufacture current data, widen freshness windows or turn stale snapshots into usable quotes. If no prior row satisfies the cutoff, the existing missing/stale fail-closed paths remain active. It does not change model features, labels, policy thresholds, risk budgets, artifact contracts or activation gates.

Limitations: PostgreSQL integration and `EXPLAIN ANALYZE` were not available. The analogous orderbook and read-only account lookup paths were subsequently corrected in release 1.35.4.

## Work package: trainer stale-candidate closure and fail-closed artifact recovery

Release 1.35.3 closes a lifecycle deadlock visible in the trainer dialog. A quality-passed inactive candidate with a missing/invalid immutable deployment-policy binding previously returned `candidate_policy_binding_missing_or_invalid` as a non-terminal `BLOCKED` result. Because the same candidate retained `activation_requested=true`, every scheduler cycle selected it again and returned before evaluating active-artifact recovery or current training-data readiness.

Implemented:

- candidate artifact path, bytes SHA-256 and deployment horizon are validated before any automatic experiment subprocess;
- missing, unreadable, hash-mismatched, horizon-invalid and policy-binding-invalid candidates are terminally closed through the existing append-only rejection/audit/outbox path;
- terminal stale-candidate closure carries `continue_scheduling=true`, allowing the same scheduler iteration to evaluate recovery/data/quality state;
- active-artifact recovery eligibility is independent from runtime baseline fallback, so production inference remains fail-closed while background/operator recovery training is allowed;
- missing, invalid-SHA, unreadable and hash-mismatched active artifacts all enter the governed recovery path;
- activation still requires a fresh candidate, passed quality gate, exact experiment evidence, current deployment-policy binding, valid artifact and active-version compare-and-swap.

The release intentionally does not convert quality-gate failure into success. `walk_forward_policy_stability_below_minimum`, `holdout_span_below_minimum`, low policy trade density and insufficient independent cohorts remain blocking evidence. A technically successful training job may therefore remain inactive. No DB migration, environment variable, policy threshold, artifact schema or risk limit changed.

Limitations: existing malformed candidates are closed only when the upgraded trainer reconciles them; PostgreSQL integration and real Windows service recovery were not run in the sandbox. Recovery training can rebuild lost bytes but cannot guarantee that a replacement model has positive out-of-sample economic evidence.



## Work package: exposure conflict isolation and latest-prior execution state

Release 1.35.4 closes three live availability/integrity defects without relaxing economic gates.

Implemented:

- exposure batches are processed item by item; stale/legacy/version-conflicting events receive terminal statuses and cannot roll back valid rows;
- browser transport retry preserves the original event identity and is limited to network, HTTP 429 and 5xx failures;
- exposure evidence is verified against its immutable opportunity across plan, signal, profile, plan version and chronology;
- orderbook and account-equity selection apply `source_time <= cutoff` and `received_at <= cutoff` before deterministic descending ordering;
- exact cutoffs are shared by plan creation, recommendation acceptance, effective capital, reconciliation and portfolio display;
- acceptance cannot proceed without a completed current-state validation object.

These changes prevent future-dated records from masking older fresh state. They do not widen freshness windows, synthesize missing data, change model features/labels, relax candidate promotion, lower EV/RR requirements or increase risk limits.

Limitations: no operator PostgreSQL database or actual candidate metrics were present, so the causes of specific quality-gate failures and realized losses remain unverified. Static typing is not clean and exact historical orderbook/operator-latency/exchange-liquidation mechanics remain incomplete.

## Work package: decision-time ticker freshness barrier

Release 1.35.5 closes the reproduced all-symbol stale-ticker availability defect without changing the freshness threshold.

Implemented:

- normal market sync no longer persists the initial universe-selection ticker payload before slow orderbook/backfill work;
- after slow work it obtains a new public Bybit ticker response and persists that response as the final market-sync boundary;
- each actual hourly inference attempt obtains and stores a new active-universe ticker batch in the same transaction immediately before signal publication;
- universe catch-up inference uses the same contract;
- a non-empty active universe with zero stored ticker rows aborts before publication;
- partial refresh remains visible and per-symbol freshness checks continue to block missing/stale rows;
- structured stale warnings disclose actual age, configured maximum, source time and receipt time.

The change preserves latest-prior query semantics from 1.35.2 and does not widen `MAX_TICKER_AGE_SECONDS`, synthesize quotes, alter model features/labels, relax candidate promotion, lower EV/RR requirements or increase risk limits.

Limitations: live PostgreSQL/Bybit execution was not available. The final barrier refreshes the single-call ticker batch; orderbook freshness remains independently fail-closed and exact historical market microstructure is still incomplete.

## Directional policy robustness (1.46.0)

Release 1.46.0 закрывает directional-masking gap. Aggregate actionable result, per-regime result и symbol/cluster jackknife могли оставаться положительными, когда LONG компенсировал систематически отрицательный SHORT либо наоборот.

Реализовано:

- exact post-actionability/post-overlap trade cohort делится на LONG и SHORT;
- для каждого направления сохраняется полный observed opportunity clock, нулевые no-trade cohorts, trade counts/fractions, opportunity-weighted realized mean R и exact actionable log loss/Brier;
- каждое фактически торгуемое направление требует минимум 5 сделок, mean R выше configured minimum и calibration в существующих absolute limits;
- schema, canonical order, counts, fractions, summaries и runtime artifact evidence проверяются fail-closed;
- policy metric schema повышена до v23, старые artifacts требуют переобучения.

Ограничения: per-symbol × direction × regime interaction robustness добавлена в 1.47.0 и усилена sparse-pool jackknife в 1.48.0, но она использует minimum-support cells и pooled sparse tail, а не causal hierarchical model. Односторонняя стратегия допустима, если единственное торгуемое направление само проходит полный контракт.
