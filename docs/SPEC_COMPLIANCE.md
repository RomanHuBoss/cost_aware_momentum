# Проверка соответствия спецификации версии 1.3

Дата проверки: 2026-06-28
Проверенный источник: `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`
Версия проекта после коррекции: 1.7.4

## Итог

Проект соответствует спецификации **частично**. Архитектурный и операторский контур реализован существенно лучше исследовательского контура: FastAPI/Uvicorn, PostgreSQL-only, отдельные worker и trainer, ручное исполнение, профили капитала, cost/risk engine, UI, audit и жизненный цикл рекомендаций присутствуют.

Версии 1.3.0–1.5.0 исправили постановку ML, добавили автоматический train → compare → activate pipeline, dataset-aware retraining и progressive history backfill. Версия 1.6.0 закрыла отдельный audit/research gap: worker сохраняет исход market signal и оценку каждой execution-plan version независимо от accept/reject. Версия 1.7.0 разрешает hourly TP/SL ambiguity по точному 1/3/5-минутному path, если он полностью доступен. Версия 1.7.1 исправляет JSONB boundary model lifecycle: candidate с отсутствующими policy metrics регистрируется как неактивный вместо аварийного orphan artifact. Версия 1.7.2 добавляет controlled runtime recovery при физической утрате active artifact. Версия 1.7.3 завершает scheduler-side recovery. Версия 1.7.4 закрывает fail-open риск в directional mathematics: инвертированные или нечисловые entry/SL/TP больше не превращаются через `abs()` в положительные расстояния и не получают исполнимый размер.

Это по-прежнему не превращает проект в доказанную production-стратегию. Полный multi-fold walk-forward, исторический стакан, live drift-control, перенос intrabar semantics в training/backtest и forward evidence остаются отдельными этапами.

## Реализовано и приведено в соответствие

| Область | Статус | Реализация |
|---|---|---|
| FastAPI/Uvicorn и PostgreSQL во всех режимах | Реализовано | `app/main.py`, `app/db/*`, Alembic, validator PostgreSQL URL |
| Отдельный worker для ingestion/inference | Реализовано | `app/workers/runner.py`; длительные задачи не выполняются в HTTP request |
| Отдельный background trainer | Реализовано | отдельный процесс, advisory lock, heartbeat/job history, fail-safe candidate lifecycle |
| Advisory-only, без отправки ордеров | Реализовано | Bybit-клиент использует public/read-only GET; ручные решения и fills сохраняются отдельно |
| Market signal отдельно от execution plan | Реализовано | `MarketSignal`, versioned `ExecutionPlan`, профили капитала |
| Cost-aware R/R, EV и sizing | Реализовано | комиссии, slippage, stop reserve, funding scenario, min-order/margin/liquidity/portfolio caps |
| Directional geometry fail-closed | Исправлено в 1.7.4 | единый validator LONG/SHORT для risk, sizing и outcome; invalid plan получает `BLOCKED_INVALID_INPUT` и нулевой размер |
| Компактная плитка, подробный диалог и glossary | Реализовано | HTML/CSS/Vanilla JS, keyboard/touch/hover подсказки, modal actions |
| Один текущий сигнал на символ | Реализовано | supersede-логика и частичный уникальный индекс PostgreSQL |
| ML-задача TP/SL/TIMEOUT, а не NO TRADE | Исправлено в 1.3.0 | direction-conditional barrier dataset и трехклассовая модель |
| Временная калибровка | Исправлено в 1.3.0 | отдельное более позднее calibration window, sigmoid OVR |
| Final holdout и purge gap | Реализовано частично | единичный chronological train/calibration/final-holdout split |
| Model registry и воспроизводимый артефакт | Реализовано | SHA256, feature/task/horizon validation, activation/rollback, одна active-модель |
| Реальный runtime active-модели | Реализовано | worker загружает registry-active artifact и обновляет его без перезапуска |
| Fail-closed для обязательных входов inference | Реализовано | stale candle/ticker, missing features, bid/ask/spec и excessive spread блокируют публикацию |
| Point-in-time cutoff при inference | Реализовано | `close_time <= cutoff`, `available_at <= cutoff`, spec `valid_from <= cutoff` |
| Фоновое переобучение и auto-activation | Реализовано с 1.4.0 | rolling window, immutable candidates, same-holdout comparison, guarded atomic activation |
| Dataset-aware retraining | Реализовано в 1.5.0 | profile rows/timestamps/symbols/coverage; triggers по backfill и universe change |
| Фактическое накопление глубокой истории | Реализовано в 1.5.0 | progressive `history_backfill` до target days с batch/page limits и учетом launch time |
| Экономический gate auto-activation | Реализовано в 1.5.0 | policy trades, realized mean R, profit factor, drawdown и incumbent-relative limits |
| JSON-safe candidate registration | Исправлено в 1.7.1 | internal fail-closed sentinels не сериализуются; non-finite metrics → `null`; registry/job/audit JSONB защищены |
| Recovery после утраты active artifact | Реализовано в 1.7.2–1.7.3 | explicit non-production baseline fallback, DEGRADED diagnostics, immediate bootstrap/recovery trigger after startup delay, short technical retry backoff, strict integrity boundary и absolute gates |
| Актуальный universe в UI/API | Исправлено в 1.5.0 | текущие карточки фильтруются по worker universe; status обновляется автоматически |
| Counterfactual outcome journal | Реализовано с intrabar refinement в 1.7.0 | confirmed hourly path; точечный 1/3/5-minute reconstruction для same-hour TP1/SL; отдельная оценка каждой plan version, audit/outbox/API/UI; missing intrabar и legacy funding timeline fail-closed |

## Частичное соответствие

| Требование | Что есть | Чего не хватает |
|---|---|---|
| Walk-forward OOS | temporal split, purge, final holdout | expanding/rolling многооконный pipeline, OOF aggregation, embargo как отдельная сущность |
| Event-driven backtest | barrier outcomes, cost reserve, NO TRADE threshold, policy metrics | entry-zone/no-fill, partial fills, simultaneous portfolio, реальная funding timeline, operator latency |
| Multi-horizon 4/8/12 | артефакт хранит horizon; можно обучить отдельные версии | одновременное сравнение нескольких горизонтов в live policy и отдельные active heads |
| Point-in-time universe research | live universe, candles, dataset profiles | исторические membership snapshots, delisted contracts и полностью point-in-time research universe |
| Liquidity/impact | spread и turnover-based caps | архив orderbook snapshots, depth VWAP и эмпирическая impact-модель |
| Fees | настраиваемая taker fee | автоматическое использование account fee-rate snapshot в обучении/backtest и live расчетах |
| Portfolio risk | общий риск, single-name/directional ограничения | устойчивые correlation clusters и factor/beta exposure |
| Надежность модели в UI | вероятности, version/calibration, training profile и причины | calibration bin, OOS analog count, confidence interval, regime statistics, live drift status |
| Автоматическая эксплуатационная защита | pre-activation ML/policy gate, сохранение incumbent | live realized-performance gate и автоматический rollback после production degradation |

## Не реализовано

- систематический PSI/feature/probability/calibration drift monitoring и автоматический fallback;
- полноценные feature registry, immutable dataset snapshots и fold-level experiment registry;
- единая 1–5-минутная разметка для training/backtest; post-event journal уже уточняет hourly ambiguity, но обучающие labels пока используют консервативное hourly правило;
- Probability of Backtest Overfitting и Deflated Sharpe Ratio;
- историческая модель фактического исполнения по стакану;
- завершенный paper/shadow forward evidence и доказательство экономического преимущества.

## Состояние машинного обучения и post-event журнала после коррекции 1.7.4

Технический ML-путь работает end-to-end:

1. Из confirmed hourly candles строятся два условных сценария на timestamp: LONG и SHORT.
2. Для каждого сценария формируется метка `TP`, `SL` или `TIMEOUT`; `NO TRADE` остается решением policy.
3. Обучается pooled logistic baseline либо `HistGradientBoostingClassifier`.
4. Вероятности калибруются на отдельном более позднем окне.
5. Final holdout оценивается Brier/log loss/ECE/AUC и cost-aware policy metrics.
6. Artifact сохраняет task, feature schema, horizon, barrier settings, metrics, SHA256 и полный `training_data_profile`.
7. Worker постепенно расширяет историческую базу активного universe до настроенной глубины.
8. Trainer сравнивает фактический текущий профиль PostgreSQL с профилем active-модели.
9. Существенный backfill или изменение symbol coverage запускает обучение досрочно, даже если новых часов мало.
10. Candidate и incumbent оцениваются на одном holdout; кандидат активируется автоматически только после абсолютных и относительных ML- и policy-gates.
11. Worker проверяет artifact hash/version/schema/horizon и загружает новую active-версию без перезапуска.
12. Провал обучения/gate не влияет на текущий inference; предыдущая модель остается доступна для rollback.
13. При физической утрате incumbent artifact non-production worker использует явно обозначенный baseline, а trainer выполняет bootstrap recovery без выдуманного incumbent comparison; production и integrity failures остаются fail-closed.
13. Отдельный worker job разрешает primary-barrier outcome по непрерывному confirmed hourly path и создает immutable plan-version estimates.
14. При hourly TP/SL ambiguity worker запрашивает только точный 1/3/5-minute window; неполный intrabar path оставляет outcome pending, а same-finest-bar ambiguity разрешается консервативно как SL.

Это означает техническую работоспособность автоматического pipeline, но не подтвержденную прибыльность. Legacy active-модель без `training_data_profile` рассматривается как требующая обновления, однако остается действующей до появления кандидата, прошедшего проверки.

## Штатный ML-цикл

При `AUTO_TRAIN_ENABLED=true` и `AUTO_TRAIN_AUTO_ACTIVATE=true` вмешательство оператора в обычное продвижение моделей не требуется:

```text
market/history sync
→ dataset profile comparison
→ background candidate training
→ common final holdout
→ ML quality gates
→ cost-aware policy gates
→ atomic activation
→ worker hot reload
```

Ручные команды сохранены для диагностики, review и rollback:

```bash
python manage.py train --horizon 8 --model-type logistic
python manage.py model-registry list
python manage.py backtest --model models/<artifact>.joblib --output reports/backtest.json
python manage.py model-registry activate --version <model-version>
```

## Вывод по готовности

- Для локального advisory/paper/shadow применения: **технически пригоден после миграции и проверок**, без утверждения прибыльности.
- Для production advisory: **условно**, только с активной обученной моделью, `ALLOW_BASELINE_MODEL=false`, отдельной БД, backup/restore и достаточным paper/shadow evidence.
- Полное соответствие исследовательским и эконометрическим требованиям спецификации: **не достигнуто**; оставшиеся пункты перечислены выше.
