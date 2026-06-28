# Model card — barrier outcome model v1

## Назначение

Модель оценивает распределение исходов `TP first`, `SL first`, `TIMEOUT` отдельно для условного LONG и SHORT на фиксированном горизонте. Она не прогнозирует `NO TRADE`: это решение последующего cost/risk policy engine.

## Доступные модели

- `logistic`: интерпретируемый pooled baseline с масштабированием и feature×direction interactions;
- `hist_gradient_boosting`: нелинейный кандидат scikit-learn;
- `deterministic_baseline`: только операционная заглушка для проверки контура, не калиброванная ML-модель.

## Данные и метки

- confirmed hourly last-price candles из PostgreSQL;
- rolling point-in-time features без использования будущих строк;
- два сценария на каждый symbol/time: LONG и SHORT;
- ATR-based stop/TP barriers;
- при одновременном касании TP и SL внутри часовой свечи используется консервативный исход SL;
- TIMEOUT закрывается по последнему close горизонта.

Ограничение: обучение пока не использует 1–5-минутный путь, исторический orderbook, исторические membership snapshots universe и publish-lag для всех внешних рядов.

## Разбиение и калибровка

Данные делятся хронологически на train, более позднее calibration window и final holdout. Между окнами создается purge gap не меньше горизонта. В каждой calibration class должна присутствовать TP/SL/TIMEOUT. Вероятности калибруются one-vs-rest sigmoid и затем нормируются.

Текущая поставка не реализует многооконный expanding/rolling walk-forward и OOF aggregation; поэтому final holdout является необходимой, но недостаточной проверкой.

## Метрики

Artifact хранит:

- multiclass log loss и Brier score;
- Brier и ECE для каждого исхода;
- macro OVR AUC;
- accuracy только как вспомогательную метрику;
- распределение классов и долю ambiguous labels;
- training-data profile: число candle rows/timestamps/символов, полный список символов, временные границы, coverage и SHA256-подписи;
- cost-aware holdout policy metrics: число сделок, trade rate, expected EV, realized mean/total R, win rate, profit factor и max drawdown;
- barrier-policy net return, win rate, max drawdown, no-trade rate и cost stress x1.5/x2 в backtest report.

Порог сделки не должен выбираться по accuracy.

## Artifact contract

Joblib bundle обязан содержать:

- `task=barrier_outcome_v1`;
- model/version/model_type;
- точный список feature names и `feature_schema_version=hourly-barrier-v1`;
- outcome classes `TP`, `SL`, `TIMEOUT`;
- horizon и параметры barriers;
- calibration version и holdout metrics.

При активации и загрузке проверяются version, SHA256, task, feature schema, classes и соответствие `DEFAULT_HORIZON_HOURS`. Legacy binary-direction artifacts отвергаются.


## Фоновое переобучение

Версия 1.5.0 использует отдельный dataset-aware `trainer` process. Он не выполняет online `partial_fit` и не перезаписывает действующую модель. Candidate строится по расписанию либо досрочно после существенного исторического backfill/изменения обучающего universe, после чего:

1. candidate и active artifact оцениваются на одном новом final holdout;
2. проверяются минимальный размер holdout, представленность TP/SL/TIMEOUT, log loss, multiclass Brier и ECE;
3. cost-aware policy на том же holdout должна дать достаточное число сделок, неотрицательный mean R, допустимые profit factor и drawdown;
4. проверяется допустимое ухудшение и требуемое улучшение относительно incumbent как по ML-, так и по policy-метрикам;
5. artifact регистрируется с SHA256, dataset profile, metrics, quality-gate decision и ссылкой на incumbent;
6. auto-activation выполняется только при успешном gate и неизменившейся active-version.

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
- hourly ambiguity в post-event журнале уточняется 1/3/5-минутным путем, но training labels пока сохраняют консервативное hourly правило;
- операторский выбор создает selection bias;
- backtest не является доказательством прибыли и не заменяет paper/shadow forward test;
- полноценные PSI/feature/probability drift gates и автоматический rollback по realized performance еще не реализованы; текущий trainer использует holdout quality gate до активации.

## Post-event counterfactual evaluation

Начиная с версии 1.6.0 worker независимо от accept/reject разрешает первичный outcome каждого market signal: `TP`, `SL` или `TIMEOUT`. Версия 1.7.0 добавляет intrabar reconstruction для hourly ambiguity. Evaluation использует directional primary-barrier семантику:

- confirmed hourly last-price candles как базовый путь;
- непрерывный путь от `event_time` до первого barrier hit или точного конца горизонта;
- hourly TP+SL вызывает точечную загрузку полного confirmed 1/3/5-минутного окна;
- неполный intrabar path оставляет outcome pending;
- TP+SL внутри одного самого мелкого бара трактуется как SL и помечается ambiguous;
- missing bar не заменяется TIMEOUT;
- outcome сохраняется один раз и не редактируется решением оператора.

Для каждой execution-plan version сохраняется отдельный estimate по ее immutable qty/risk/cost snapshot. Комиссии входа/выхода применяются к соответствующим notionals, stop-gap reserve — только к SL. Funding включает только settlement timestamps, пересеченные гипотетическим holding period, когда timeline присутствует в snapshot. Legacy-планы без такого timeline получают `FUNDING_UNAVAILABLE` и не получают counterfactual R.

Начиная с 1.7.6 non-finite qty/stress loss, отрицательные либо non-finite costs и поврежденный funding timeline не создают `NaN`-метрики и не прерывают worker batch. Такая plan version получает terminal `INVALID_INPUT`, нулевые оценочные денежные значения, `counterfactual_r=null` и диагностический `validation_error`. Валидный market outcome сохраняется отдельно; это не исправляет исходные данные и не превращает нулевую оценку в фактический P&L.

Этот журнал предназначен для анализа selection bias, calibration и policy quality. Он не является realized P&L ручной сделки, не использует фактические fills и пока не служит автоматическим live rollback gate.
