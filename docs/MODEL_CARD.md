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

## Активация и rollback

Обучение по умолчанию регистрирует artifact как неактивный. После review:

```bash
python manage.py model-registry activate --version <version>
```

Одновременно допускается только одна active-модель. Worker перечитывает registry каждые `MODEL_REFRESH_SECONDS`. Активация предыдущей версии выполняет rollback и создает audit/outbox event.

## Baseline policy

В paper/development baseline может быть разрешен через `ALLOW_BASELINE_MODEL=true`, но каждая рекомендация получает предупреждение. В production validator требует `ALLOW_BASELINE_MODEL=false`; отсутствие валидной active-модели делает запуск/readiness неуспешным.

## Известные риски

- калибровка и costs деградируют при смене режима;
- cross-sectional dependence уменьшает эффективный размер выборки;
- hourly ambiguity создает консервативную, но грубую метку;
- операторский выбор создает selection bias;
- backtest не является доказательством прибыли и не заменяет paper/shadow forward test;
- drift monitoring и автоматический fallback еще не реализованы.
