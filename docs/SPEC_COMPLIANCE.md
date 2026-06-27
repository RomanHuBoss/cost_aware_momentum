# Проверка соответствия спецификации версии 1.3

Дата проверки: 2026-06-27
Проверенный источник: `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`
Версия проекта после коррекции: 1.4.0

## Итог

Проект соответствует спецификации **частично**. Архитектурный и операторский контур реализован существенно лучше исследовательского контура: FastAPI/Uvicorn, PostgreSQL-only, отдельный worker, ручное исполнение, профили капитала, cost/risk engine, UI, audit и жизненный цикл рекомендаций присутствуют. До исправления ML-контур не соответствовал заявленной постановке: обучалась бинарная модель направления, а вероятности TP/SL/timeout формировались эвристически; зарегистрированная active-модель не гарантированно загружалась worker.

Версия 1.4.0 дополнительно закрывает эксплуатационный разрыв фонового переобучения: отдельный trainer формирует кандидата, сравнивает его с incumbent на одном holdout и безопасно активирует только после quality gate. Это по-прежнему не превращает проект в доказанную production-стратегию. Полный walk-forward, исторический стакан, drift-control, counterfactual outcomes и forward evidence остаются отдельными этапами.

## Реализовано и приведено в соответствие

| Область | Статус | Реализация |
|---|---|---|
| FastAPI/Uvicorn и PostgreSQL во всех режимах | Реализовано | `app/main.py`, `app/db/*`, Alembic, validator PostgreSQL URL |
| Отдельный worker для ingestion/inference | Реализовано | `app/workers/runner.py`; длительные задачи не выполняются в HTTP request |
| Advisory-only, без отправки ордеров | Реализовано | Bybit-клиент использует public/read-only GET; ручные решения и fills сохраняются отдельно |
| Market signal отдельно от execution plan | Реализовано | `MarketSignal`, versioned `ExecutionPlan`, профили капитала |
| Cost-aware R/R, EV и sizing | Реализовано | комиссии, slippage, stop reserve, funding scenario, min-order/margin/liquidity/portfolio caps |
| Компактная плитка, подробный диалог и glossary | Реализовано | HTML/CSS/Vanilla JS, keyboard/touch/hover подсказки, modal actions |
| Один текущий сигнал на символ | Реализовано | supersede-логика и частичный уникальный индекс PostgreSQL |
| ML-задача TP/SL/TIMEOUT, а не NO TRADE | Исправлено в 1.3.0 | direction-conditional barrier dataset и трехклассовая модель |
| Временная калибровка | Исправлено в 1.3.0 | отдельное более позднее calibration window, sigmoid OVR |
| Final holdout и purge gap | Реализовано частично | единичный chronological train/calibration/final-holdout split |
| Model registry и воспроизводимый артефакт | Исправлено в 1.3.0 | SHA256, feature/task/horizon validation, явная activation/rollback, одна active-модель |
| Реальный runtime активной модели | Исправлено в 1.3.0 | worker загружает registry-active artifact, проверяет hash/version/horizon и обновляет без перезапуска |
| Fail-closed для обязательных входов inference | Исправлено в 1.3.0 | пропуск публикации при stale candle/ticker, missing features, missing bid/ask/spec, excessive spread |
| Point-in-time cutoff при inference | Исправлено в 1.3.0 | `close_time <= cutoff`, `available_at <= cutoff`, spec `valid_from <= cutoff` |
| Readiness модели и worker | Усилено в 1.3.0 | active registry version должна совпадать с runtime; hash и свежесть market sync проверяются |
| Фоновое переобучение | Реализовано в 1.4.0 | отдельный trainer, weekly default, minimum-new-data gate, immutable candidates, same-holdout comparison и guarded auto-activation |

## Частичное соответствие

| Требование | Что есть | Чего не хватает |
|---|---|---|
| Walk-forward OOS | temporal split, purge, final holdout | expanding/rolling многооконный pipeline, OOF aggregation, embargo как отдельная сущность |
| Event-driven backtest | barrier outcomes, cost reserve, NO TRADE threshold, cost x1.5/x2 | entry-zone/no-fill, partial fills, simultaneous portfolio, реальная funding timeline, operator latency |
| Multi-horizon 4/8/12 | артефакт хранит horizon; можно обучить отдельные версии | одновременное сравнение нескольких горизонтов в live policy и отдельные active heads |
| Point-in-time universe research | live universe и исторические candles | исторические membership snapshots, delisted contracts и полностью point-in-time research universe |
| Liquidity/impact | spread и turnover-based caps | архив orderbook snapshots, depth VWAP и эмпирическая impact-модель |
| Fees | настраиваемая taker fee | автоматическое использование account fee-rate snapshot в расчетах |
| Portfolio risk | общий риск, single-name/directional ограничения | устойчивые correlation clusters и factor/beta exposure |
| Надежность модели в UI | вероятности, version/calibration и причины | calibration bin, OOS analog count, confidence interval, regime statistics, drift status |
| Counterfactual outcome | сигналы сохраняются независимо от решения | автоматический post-event outcome для каждого сигнала и каждой plan version |

## Не реализовано

- систематический PSI/feature/probability/calibration drift monitoring и автоматический fallback;
- scheduler переобучения с approval gate;
- полноценные feature registry, dataset snapshots и fold-level experiment registry;
- 1–5-минутное восстановление порядка касаний TP/SL; применяется консервативное правило по часовому OHLC;
- Probability of Backtest Overfitting и Deflated Sharpe Ratio;
- историческая модель фактического исполнения по стакану;
- завершенный paper/shadow forward evidence и доказательство экономического преимущества.

## Состояние машинного обучения

### До коррекции

ML нельзя было считать работающим в смысле спецификации:

1. `training.py` обучал бинарное направление будущей доходности, а не TP-first/SL-first/timeout.
2. Runtime преобразовывал вероятность направления в `p_tp/p_sl/p_timeout` эвристически.
3. Worker по умолчанию использовал детерминированный baseline.
4. Запись `active=true` в PostgreSQL не гарантировала, что worker загрузил именно этот artifact.
5. Readiness не сверял registry version с фактически загруженной моделью.
6. Backtest оценивал направление будущей доходности, а не direction-specific barrier policy.

### После коррекции 1.4.0

Технический ML-путь работает end-to-end:

1. Из confirmed hourly candles строятся два условных сценария на timestamp: LONG и SHORT.
2. Для каждого сценария формируется метка `TP`, `SL` или `TIMEOUT`.
3. Обучается pooled logistic baseline либо `HistGradientBoostingClassifier`.
4. Для pooled LONG/SHORT модели добавляются feature×direction interactions.
5. Вероятности калибруются на отдельном более позднем окне.
6. Final holdout оценивается Brier/log loss/ECE/AUC и barrier-policy метриками.
7. Artifact сохраняет task, feature schema, horizon, barrier settings, metrics и SHA256.
8. Модель регистрируется неактивной; активация выполняется отдельно после проверки.
9. Worker проверяет artifact hash/version/schema/horizon и публикует реальные прогнозы модели.
10. `NO TRADE` остается решением cost/risk policy, а не классом модели.

Это означает техническую работоспособность pipeline, но не подтвержденную прибыльность. Без достаточной истории обучение завершится ошибкой; без явно активированной модели paper-режим продолжит использовать baseline. В production baseline теперь запрещается конфигурацией.

## Рекомендуемый цикл ML

```bash
python manage.py train --horizon 8 --model-type logistic
python manage.py model-registry list
python manage.py backtest --model models/<artifact>.joblib --output reports/backtest.json
python manage.py model-registry activate --version <model-version>
```

После активации worker загрузит новую версию не позднее `MODEL_REFRESH_SECONDS`. Активация старой версии той же командой является rollback.

## Вывод по готовности

- Для локального advisory/paper/shadow применения: **технически пригоден после миграции и проверок**, с явной маркировкой baseline и без утверждения прибыльности.
- Для production advisory: **условно**, только с обученной активной моделью, `ALLOW_BASELINE_MODEL=false`, отдельной БД, backup/restore и paper/shadow evidence.
- Полное соответствие исследовательским и эконометрическим требованиям спецификации: **не достигнуто**; оставшиеся пункты перечислены выше.
