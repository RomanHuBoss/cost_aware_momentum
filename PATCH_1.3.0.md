# Patch 1.3.0 — specification and ML alignment

## Главная коррекция

Предыдущая поставка не реализовывала ML-постановку спецификации end-to-end: обучалась бинарная direction-модель, TP/SL/timeout вероятности достраивались эвристически, а registry-active artifact не был надежно связан с runtime worker.

## Изменения

- direction-conditional triple-barrier dataset для LONG и SHORT;
- трехклассовые исходы TP/SL/TIMEOUT;
- logistic baseline и HistGradientBoosting candidate;
- feature×direction interactions для pooled модели;
- отдельное временное calibration window и sigmoid calibration;
- final holdout metrics: log loss, Brier, ECE, AUC;
- barrier-policy backtest с cost stress x1.5/x2;
- strict artifact contract и отказ от legacy binary models;
- SHA/version/schema/classes/horizon verification;
- PostgreSQL registry как источник active model;
- явная activation/rollback CLI и audit event;
- частичный уникальный индекс: одна active-модель;
- periodic hot reload worker;
- readiness сверяет registry, runtime, hash и свежесть market sync;
- point-in-time candle/spec cutoff при inference;
- fail-closed публикация при stale/missing обязательных данных;
- production config запрещает demo seed, baseline и default credentials;
- обновлены документация, model card и честная матрица соответствия.

## Миграция

```bash
python manage.py migrate
```

## ML workflow

```bash
python manage.py train --horizon 8 --model-type logistic
python manage.py model-registry list
python manage.py backtest --model models/<artifact>.joblib
python manage.py model-registry activate --version <version>
```

## Важное ограничение

Патч делает ML-контур технически согласованным, но не доказывает прибыльность. Полный walk-forward, historical orderbook execution, drift monitoring, counterfactual outcomes и forward evidence остаются обязательными последующими этапами.
