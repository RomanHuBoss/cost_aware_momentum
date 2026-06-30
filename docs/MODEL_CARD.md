# Model card — barrier outcome model v1

## Terminal target contract in 1.8.15

The model predicts `TP / SL / TIMEOUT` against one ATR-based TP barrier per direction. Production EV/R, position sizing, labels and counterfactual outcomes use that same TP1. The UI therefore exposes TP1 at 100%. Weighted TP1/TP2 execution remains an unimplemented research feature rather than an implied second model outcome.


## Policy metric contract v5 (1.8.14)

`exit-time-open-gap-propagated-cohort-weighted-v5` adds `policy_cohorts`. Mean realized R and expected EV/R are equal-weight means of hourly decision cohorts, not raw trade means. Profit factor is derived from net portfolio contributions grouped by modeled exit time. The quality gate requires both `policy_trades` and `policy_cohorts` to meet `AUTO_TRAIN_MIN_POLICY_TRADES`; v4 artifacts/metrics must be reevaluated before comparison. This removes cross-sectional pseudo-replication but does not prove profitability or independence across market regimes.

## Назначение

Модель оценивает распределение исходов `TP first`, `SL first`, `TIMEOUT` отдельно для условного LONG и SHORT на фиксированном горизонте. Она не прогнозирует `NO TRADE`: это решение последующего cost/risk policy engine.

Начиная с 1.8.4 runtime передает policy layer оба распределения. Окончательное направление выбирается по фактическому net `EV/R` с текущими executable bid/ask, комиссиями, slippage, funding и barrier geometry. Предварительная модельная utility используется только как диагностический score и не участвует в production tie-break: порядок выбора зафиксирован как `EV/R → net RR → LONG`. Начиная с 1.8.5 live stop/TP1 geometry и compatibility score используют `stop_atr_multiplier` / `tp_atr_multiplier` активного artifact, что устраняет latent train/serve skew при нестандартных barriers.

## Доступные модели

- `logistic`: интерпретируемый pooled baseline с масштабированием и feature×direction interactions;
- `hist_gradient_boosting`: нелинейный кандидат scikit-learn;
- `deterministic_baseline`: только операционная заглушка для проверки контура, не калиброванная ML-модель.

## Данные и метки

- confirmed hourly last-price candles из PostgreSQL;
- rolling point-in-time features без использования будущих строк; начиная с 1.8.8 gap, duplicate или invalid OHLCV сбрасывает stateful EMA/ATR/rolling segment, а полный 24-часовой lookback обязан состоять из последовательных валидных hourly timestamps;
- два сценария на каждый symbol/time: LONG и SHORT;
- ATR-based stop/TP barriers;
- при одновременном касании TP и SL внутри часовой свечи используется консервативный исход SL;
- TIMEOUT закрывается по последнему close горизонта.

Ограничение: обучение пока не использует 1–5-минутный путь, исторический orderbook, исторические membership snapshots universe и publish-lag для всех внешних рядов.

## Разбиение и калибровка

До split dataset builder исключает timestamp, если 24-часовой feature-lookback или следующие N label-candles содержат пропуск, дубликат либо невалидную OHLCV-геометрию; stateful feature calculations не пересекают такой разрыв, а счетчики сохраняются в `hourly_continuity`. Данные делятся хронологически на train, более позднее calibration window и final holdout. Начиная с 1.7.10 каждая строка хранит фактический `label_end_time`: train/calibration observation исключается, если ее будущий barrier-window достигает следующего окна. После границы дополнительно сохраняется embargo не меньше горизонта в часах. Отсутствующий, невалидный или не более поздний `label_end_time` блокирует split fail-closed. В каждой calibration class должна присутствовать TP/SL/TIMEOUT. Вероятности калибруются one-vs-rest sigmoid и затем нормируются.

Текущая поставка не реализует многооконный expanding/rolling walk-forward и OOF aggregation; поэтому final holdout является необходимой, но недостаточной проверкой.

## Метрики

Artifact хранит:

- multiclass log loss и Brier score; начиная с 1.7.9 log loss индексирует probability columns по объявленному artifact-порядку `TP / SL / TIMEOUT`, а не по лексикографической сортировке labels;
- Brier и ECE для каждого исхода;
- macro OVR AUC;
- accuracy только как вспомогательную метрику;
- raw и calibrated log loss, улучшение после calibration, class-prior benchmark, uniform benchmark и skill относительно class prior;
- распределение классов и долю ambiguous labels;
- training-data profile: число candle rows/timestamps/символов, полный список символов, временные границы, coverage и SHA256-подписи;
- cost-aware holdout policy metrics: число сделок, trade rate, expected EV, realized mean/total R, win rate, profit factor и max drawdown; начиная с 1.8.8 realized total R/drawdown агрегируются по modeled exit time и equal-weight decision cohorts; начиная с 1.8.9 каждый cohort до оценки обязан содержать ровно одну LONG- и одну SHORT-строку;
- barrier-policy net return, win rate, max drawdown, no-trade rate и cost stress x1.5/x2 в backtest report; начиная с 1.8.5 backtest применяет cost-aware EV/R selection, exit-notional-aware fees и H неперекрывающихся capital sleeves.

Порог сделки не должен выбираться по accuracy.

## Artifact contract

Joblib bundle обязан содержать:

- `task=barrier_outcome_v1`;
- model/version/model_type;
- точный список feature names и exact current `feature_schema_version=hourly-barrier-contiguous-v3`; artifact со старым/неизвестным schema marker не загружается как совместимый;
- outcome classes `TP`, `SL`, `TIMEOUT`;
- horizon и параметры barriers;
- calibration version и holdout metrics;
- для новых artifacts `label_path_schema_version=ohlc-open-first-stop-gap-v1`;
- `temporal_split_schema=decision-and-label-end-purged-v3`, `label_data_end` и diagnostics `hourly_continuity`, отделенные от scheduler-поля `training_end`;

При активации и загрузке проверяются version, SHA256, task, exact feature schema, feature names/classes, positive integer horizon, соответствие `DEFAULT_HORIZON_HOURS` и non-empty calibration version. Runtime обязан передать полный finite feature vector; missing/NaN/Infinity feature не заменяется нулем. Начиная с 1.8.8 каждая probability row дополнительно обязана быть finite TP/SL/TIMEOUT simplex; malformed artifact output отвергается fail-closed. Legacy binary-direction artifacts отвергаются.

Начиная с 1.8.9 training dataset формирует directional observation атомарно: если barrier geometry одного направления невалидна, не сохраняется и второе направление того же `decision_time/symbol`. Chronological split, holdout policy и backtest повторно требуют точную пару `LONG + SHORT`, чтобы candidate/incumbent gates не оценивались на входах, недопустимых для production policy.

Начиная с 1.8.10 каждая observation до directional ranking проходит единый metadata contract: заявленное направление совпадает с pair key, target входит в `TP/SL/TIMEOUT`, barrier/return finite, `exit_index` и `label_end_time` валидны, а при наличии path metadata return согласован с barrier outcome. Это не позволяет поврежденной строке скрыться только потому, что другая direction выиграла ranking. Class distribution должна содержать exact finite counts/proportions, а incumbent-relative gate блокируется при non-finite ML/policy metric. Profit factor строится из тех же cohort-weighted realized contributions, что equity/drawdown; concurrency average включает наблюдаемые idle intervals.
Начиная с 1.8.11 TP return обязан совпадать с take-profit barrier в tolerance, TIMEOUT обязан оставаться строго между TP/SL barriers, а `label_end_time` — точно равняться `decision_time + horizon`. Holdout policy делит realized R contribution на H capital sleeves и публикует schema `exit-time-horizon-sleeves-v2`; candidate/incumbent без совпадающих schema/horizon не допускаются к auto-activation. Это требует перерасчета policy metrics после обновления.

Начиная с 1.8.12 label path использует schema `ohlc-open-first-stop-gap-v1`: полный OHLC валидируется, `open` разрешается раньше unordered `high/low`, adverse SL gap получает наблюдаемую цену открытия, favorable TP gap ограничивается target, а `exit_at_open` сохраняет точный modeled exit time. В 1.8.13 исправлена потеря этого поля в chronological split: metadata без boolean `exit_at_open` отклоняется fail-closed, а promotion metrics публиковали `exit-time-open-gap-propagated-horizon-sleeves-v4`. В 1.8.14 текущий contract повышен до `exit-time-open-gap-propagated-cohort-weighted-v5`. Realized SL использует фактический return, stop-gap reserve после известного выхода уменьшается на уже встроенный в цену gap; v3 и v4 нельзя смешивать без пересчета.


## Фоновое переобучение

Версия 1.5.0 использует отдельный dataset-aware `trainer` process. Он не выполняет online `partial_fit` и не перезаписывает действующую модель. Candidate строится по расписанию либо досрочно после существенного исторического backfill/изменения обучающего universe, после чего:

1. candidate и active artifact оцениваются на одном новом final holdout;
2. проверяются минимальный размер holdout, представленность TP/SL/TIMEOUT, log loss, multiclass Brier и ECE;
3. cost-aware policy на том же holdout должна дать достаточное число сделок, неотрицательный mean R, допустимые profit factor и drawdown;
4. проверяется допустимое ухудшение и требуемое улучшение относительно incumbent как по ML-, так и по policy-метрикам;
5. artifact регистрируется с SHA256, dataset profile, metrics, quality-gate decision и ссылкой на incumbent;
6. auto-activation выполняется только при успешном gate и неизменившейся active-version; начиная с 1.7.8 регистрация нового candidate, переключение active-row, audit и outbox выполняются одной транзакцией.

Обучение запускается отдельным процессом, поэтому fitting scikit-learn не блокирует FastAPI и hourly inference. Не прошедший gate candidate остается в registry неактивным и может быть изучен вручную. Начиная с 1.7.1 отсутствующие policy metrics и non-finite comparison deltas сохраняются в registry как JSON `null`; внутренние fail-closed сравнения и причины gate при этом не ослабляются.

## Активация и rollback

Фоновое обучение по умолчанию само активирует только улучшившийся candidate. Ручная команда остается для review и rollback:

```bash
python manage.py model-registry activate --version <version>
```

Одновременно допускается только одна active-модель. Worker перечитывает registry каждые `MODEL_REFRESH_SECONDS`. Активация предыдущей версии выполняет rollback и создает audit/outbox event.

Для orphan artifact, который существует в `MODEL_DIR`, но отсутствует в registry после прерванной регистрации, версия 1.7.7 предоставляет контролируемую команду recovery. Она доступна только в non-production при отсутствии usable trained active model, повторно валидирует bundle и абсолютные ML/policy gates, затем использует обычную registry activation. Наличие файла само по себе никогда не означает активацию.

## Baseline policy

В non-production baseline может быть разрешен через `ALLOW_BASELINE_MODEL=true`, но каждая рекомендация получает предупреждение, worker heartbeat имеет статус `DEGRADED`, а UI явно показывает effective runtime. Baseline используется при отсутствии active registry row, active deterministic baseline и при физическом отсутствии файла active registry artifact. Это не распространяется на повреждение, hash mismatch или несовместимый bundle. Начиная с 1.7.3 trainer распознает такое состояние до обычной dataset-aware scheduling: после startup delay запускается bootstrap/recovery training, несвязанные старые failures не блокируют новый recovery episode, а повторная техническая ошибка получает короткий `AUTO_TRAIN_RECOVERY_RETRY_MINUTES`. Утраченный incumbent может быть заменен только кандидатом, прошедшим абсолютные gates. В production validator требует `ALLOW_BASELINE_MODEL=false`; отсутствие валидной active-модели делает запуск/readiness неуспешным.

## Известные риски

- калибровка и costs деградируют при смене режима;
- cross-sectional dependence уменьшает эффективный размер выборки;
- после упорядоченного open hourly ambiguity в post-event журнале уточняется 1/3/5-минутным путем; если полного intrabar path нет, дальнейшие TP/SL touches внутри бара остаются консервативно неупорядоченными;
- разрывы и invalid hourly bars исключаются и сбрасывают feature state, но pipeline пока не выполняет автоматическое targeted backfill/repair конкретного gap перед training;
- операторский выбор создает selection bias;
- backtest не является доказательством прибыли и не заменяет paper/shadow forward test; capital sleeves устраняют overlap leverage, но не моделируют intrahorizon mark-to-market, no-fill, partial fills и historical orderbook;
- полноценные PSI/feature/probability drift gates и автоматический rollback по realized performance еще не реализованы; текущий trainer использует holdout quality gate до активации.

## Post-event counterfactual evaluation

Начиная с версии 1.6.0 worker независимо от accept/reject разрешает первичный outcome каждого market signal: `TP`, `SL` или `TIMEOUT`. Версия 1.7.0 добавляет intrabar reconstruction для hourly ambiguity. Evaluation использует directional primary-barrier семантику:

- confirmed hourly last-price candles как базовый путь; open проверяется и разрешается раньше unordered high/low;
- непрерывный hourly path от `event_time` до первого barrier hit или точного конца горизонта; поскольку `publish_time` может быть позже часовой границы, первый hourly bar содержит небольшой pre-publication interval, который нельзя устранить без tick/actual-fill path;
- hourly TP+SL вызывает точечную загрузку полного confirmed 1/3/5-минутного окна;
- неполный intrabar path оставляет outcome pending;
- TP+SL внутри одного самого мелкого бара трактуется как SL и помечается ambiguous;
- missing bar не заменяется TIMEOUT;
- outcome сохраняется один раз и не редактируется решением оператора.

Для каждой execution-plan version сохраняется отдельный estimate по ее immutable qty/risk/cost snapshot. Комиссии входа/выхода применяются к соответствующим notionals. Для SL stop-gap reserve уменьшается на adverse gap, уже встроенный в наблюдаемую modeled exit price; остаток сохраняется как консервативный буфер. Funding включает только settlement timestamps, пересеченные гипотетическим holding period, когда timeline присутствует в snapshot. Legacy-планы без такого timeline получают `FUNDING_UNAVAILABLE` и не получают counterfactual R.

Начиная с 1.7.6 non-finite qty/stress loss, отрицательные либо non-finite costs и поврежденный funding timeline не создают `NaN`-метрики и не прерывают worker batch. Такая plan version получает terminal `INVALID_INPUT`, нулевые оценочные денежные значения, `counterfactual_r=null` и диагностический `validation_error`. Валидный market outcome сохраняется отдельно; это не исправляет исходные данные и не превращает нулевую оценку в фактический P&L.

Этот журнал предназначен для анализа selection bias, calibration и policy quality. Он не является realized P&L ручной сделки, не использует фактические fills и пока не служит автоматическим live rollback gate.
