# Specification Compliance

Состояние на 2026-07-05. Статусы основаны на фактическом коде release 1.24.0, а не на заявлении о полной реализации спецификации.

| Требование | Статус | Доказательство / ограничение |
|---|---|---|
| Advisory-only, read-only Bybit | Реализовано | `app/bybit/client.py` содержит GET market/account reads; order mutation methods отсутствуют. |
| PostgreSQL-only | Реализовано | SQLAlchemy/PostgreSQL models и Alembic; SQLite fallback отсутствует. |
| Point-in-time confirmed hourly data | Реализовано | `Candle.close_time`, `available_at`, confirmed semantics, temporal tests. |
| LONG/SHORT executable-side entry semantics | Частично реализовано 1.10.0 | Direction-specific adverse spread proxy. Exact historical bid/ask и operator latency отсутствуют. |
| Historical orderbook depth/VWAP/no-fill/partial-fill | Частично реализовано 1.14.0 | Forward point-in-time REST snapshots сохраняются в PostgreSQL; plan/acceptance используют direction-aware bounded-depth simulation, complete-fill VWAP и FULL/PARTIAL/NO_FILL evidence. Исторический backfill до 1.14.0, RPI/queue position, limit-order fill probability и реальный partial-fill lifecycle отсутствуют; поэтому model/backtest gap не считается закрытым. |
| Historical funding tied to actual settlements in research labels | Реализовано 1.22.0 для observed settlement и interval history | Progressive backfill сохраняет фактические settlement timestamps; training/backtest агрегируют только события `(entry, actual_exit]`, используют interval, действовавший по `InstrumentSpecHistory`, и fail-closed при пропусках на стабильных участках и после наблюдаемой смены cadence. Будущая фактическая ставка не участвует в ex-ante selection. Historical forecast snapshots и interval до первой локально наблюдаемой spec-записи не реконструируются. |
| Rolling/expanding walk-forward | Реализовано 1.11.0 | Три purged expanding folds внутри development period, fresh fit/calibration на каждом fold и отдельный final holdout. Не является nested CV/PBO. |
| Operator-selection bias correction | Частично реализовано 1.21.0 | Prospective ex-ante opportunity ledger, immutable first UI-exposure evidence и ACCEPT/REJECT/NO_DECISION сохранены. Denominator теперь включает только plan versions, действительно показанные first-party UI после ≥50% видимости в активной вкладке в течение ≥1 секунды; exposure time задаёт chronological ordering, coverage/anomalies публикуются и низкое coverage блокирует IPSW. Signal-atomic OOS propensity split и cluster moving-block intervals сохранены. Это не causal treatment model: eye tracking, comprehension, latent operator state, propensity refit внутри bootstrap, API/CLI exposures и pre-1.15 opportunities отсутствуют. |
| Intrahorizon MTM and liquidation simulation | Частично реализовано 1.13.0 | Training/backtest требуют exact hourly Bybit mark-price path, рассчитывают directional MAE/MFE/minimum equity и conservative isolated-margin liquidation proxy с actual funding timing; future mark path влияет только на realized evidence. Не реализованы sub-hour ordering, historical MMR/risk tiers, liquidation fees, cross/portfolio margin, ADL и точная exchange fill/liquidation mechanics. |
| OI/basis/funding/liquidity/context features | Частично реализовано 1.22.0 | Model использует 10 OHLCV-derived + 7 point-in-time context features: OI changes 1h/24h, mark/index basis и delta, latest settled funding/age с interval effective at decision time и turnover/OI liquidity proxy. Exact OI/basis и funding anchor обязательны; same-split ablation и walk-forward non-inferiority входят в gate. Historical local receipt timestamps, funding forecasts, orderbook-depth features, cross-asset context и richer liquidity regimes отсутствуют. |
| PBO, Deflated Sharpe, full experiment ledger | Частично реализовано 1.20.0 | Prospective append-only trial ledger, aligned returns, contiguous CSCV/PBO, HAC-adjusted DSR и horizon-floored moving-block intervals сохранены. Новая family до первого `STARTED` требует immutable preregistration: hypothesis, exact cohort fingerprint/horizon, exhaustive fixed/search contract, primary metric, thresholds, stopping rule и exclusions. Trial outside contract и post-result policy override блокируются. Pre-1.18 trials не реконструируются; pre-1.20 families не считаются preregistered; external trusted timestamp, conditional search spaces, automated exclusion coding и automatic model-promotion gate отсутствуют. |
| Production drift monitoring | Частично реализовано 1.23.0 | Active-version monitor сравнивает production с immutable final-holdout reference: coverage/missingness, feature/probability PSI, selected-direction log-loss/Brier и actionability density. Calibration использует только full-horizon mature signals; early TP/SL незрелых сигналов исключаются, unresolved mature outcomes и invalid maturity metadata блокируют evidence. Failed jobs/insufficient evidence дают `BLOCKED`, critical drift деградирует heartbeat. Multivariate tests, adaptive control limits и automated rollback отсутствуют. |
| Candidate/live recommendation attrition diagnostics | Реализовано 1.24.0 prospectively | Каждый background training attempt, `symbol × event_time` inference opportunity и initial execution plan получает terminal outcome/cause; retries дедуплицируются, incomplete/legacy/conflicting evidence блокируется. История до 1.24.0 не реконструируется; это diagnostic attribution, а не causal decomposition или автоматическое изменение gates. |


## Work package: candidate/live recommendation attrition diagnostics

Release 1.24.0 добавляет prospective audit trail для ответа на вопрос, где именно теряются candidate и live opportunities:

- каждый selected symbol в hourly/catch-up job получает один terminal outcome с `event_time` и stable reason code;
- повторные попытки дедуплицируются по `symbol × event_time`, а восстановление после первоначального skip считается отдельно;
- каждый initial execution plan сохраняет schema, terminal stage, primary/contributing reason codes и limiting cap;
- background trainer attempts агрегируются как training failed, quality-gate failed, activated или activation skipped;
- quality-gate reasons группируются по model quality, temporal validation, policy economics, incumbent-relative и evidence integrity;
- exact denominators, duplicate/conflicting records и gate/activation consistency проверяются fail-closed;
- CLI и daily report публикуют единый `candidate-live-attrition-report-v1`.

Ограничения: evidence накапливается только после upgrade 1.24.0; report не является causal Shapley/decomposition model, не оценивает упущенную прибыль и не меняет thresholds, active artifact или risk policy. Multi-label contributing reasons нельзя суммировать как независимые потери.

## Work package: maturity-aware delayed-label drift calibration

Release 1.23.0 устраняет right-censoring production calibration: TP/SL может разрешиться до конца horizon, тогда как TIMEOUT появляется только после полного окна. Реализовано:

- feature/probability PSI и actionability сохраняют полный active-version monitoring window;
- calibration cohort включает только сигналы с `event_time + horizon_hours <= generated_at`;
- early resolved outcomes незрелых сигналов исключаются и отдельно считаются;
- каждый mature signal обязан иметь один outcome, иначе report/calibration получают `BLOCKED`;
- report schema `production-drift-report-v2` раскрывает `full-horizon-mature-signal-outcomes-v1` coverage;
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

