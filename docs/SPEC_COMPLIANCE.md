# Проверка соответствия спецификации версии 1.3

## 1.8.15 status change

Strengthened executable-quote and plan-contract integrity: all relevant paths reject missing/non-finite/crossed bid/ask; malformed ticker items are isolated; UI entry-state uses the marketable side; and the published plan no longer advertises an unmodeled TP2 partial exit. PostgreSQL-only and advisory-only boundaries are unchanged.

Дата проверки: 2026-06-30
Проверенный источник: `docs/source/Cost_aware_hourly_ML_momentum_specification.docx`
Версия проекта после коррекции: 1.8.15

## Итог

Проект соответствует спецификации **частично**. Архитектурный и операторский контур реализован существенно лучше исследовательского контура: FastAPI/Uvicorn, PostgreSQL-only, отдельные worker и trainer, ручное исполнение, профили капитала, cost/risk engine, UI, audit и жизненный цикл рекомендаций присутствуют.

Версии 1.3.0–1.5.0 исправили постановку ML, добавили автоматический train → compare → activate pipeline, dataset-aware retraining и progressive history backfill. Версия 1.6.0 закрыла отдельный audit/research gap: worker сохраняет исход market signal и оценку каждой execution-plan version независимо от accept/reject. Версия 1.7.0 разрешает hourly TP/SL ambiguity по точному 1/3/5-минутному path, если он полностью доступен. Версия 1.7.1 исправляет JSONB boundary model lifecycle: candidate с отсутствующими policy metrics регистрируется как неактивный вместо аварийного orphan artifact. Версия 1.7.2 добавляет controlled runtime recovery при физической утрате active artifact. Версия 1.7.3 завершает scheduler-side recovery. Версия 1.7.4 закрывает fail-open риск в directional mathematics: инвертированные или нечисловые entry/SL/TP больше не превращаются через `abs()` в положительные расстояния и не получают исполнимый размер. Версия 1.7.5 закрывает соседнюю числовую boundary-проблему sizing: non-finite capital/risk/margin/caps, невалидные instrument constraints и отрицательные cost reserves блокируются до арифметики и не создают исключение либо исполнимый план. Версия 1.7.6 распространяет тот же fail-closed контракт на post-event valuation каждой execution-plan version: поврежденный sizing/cost/funding snapshot получает terminal `INVALID_INPUT` с нулевыми результатами и не останавливает batch. Версия 1.7.7 закрывает операционный разрыв между файловой системой и model registry: UI показывает inactive/rejected/orphan artifact, а explicit recovery CLI может зарегистрировать и активировать orphan только после повторной metadata-проверки и абсолютного quality gate в non-production. Версия 1.7.8 устраняет соседнее транзакционное окно: для нового candidate регистрация, деактивация incumbent, activation, audit и outbox теперь коммитятся или откатываются вместе. Версия 1.7.9 исправляет classification-metric boundary: multiclass `log_loss` больше не сопоставляет столбцы `TP / SL / TIMEOUT` с лексикографическим порядком `SL / TIMEOUT / TP`; quality gate получает class-order-safe значение и диагностические raw/calibrated/prior/uniform benchmarks. Версия 1.7.10 закрывает temporal leakage при разреженной истории: split использует фактический конец будущего label-window. Версия 1.7.11 устраняет оставшуюся semantic drift: features и labels строятся только по строго последовательным hourly timestamps, а затронутые gaps/duplicates блокируются в live и исключаются из research dataset. Версия 1.7.12 закрывает temporal integrity gap ручного журнала: partial/full close не может быть записан раньше entry или последнего фактического fill. Версия 1.8.4 закрывает production/policy mismatch: worker больше не выбирает направление по фиксированной беззатратной utility до расчета net economics; оба directional-сценария сравниваются по публикуемому net `EV/R`. Версия 1.8.5 переносит ту же policy в research backtest, исправляет exit-notional fee normalization, overlap compounding через H capital sleeves, concurrency accounting, funding start boundary и применение artifact barrier multipliers в live geometry.
Версия 1.8.0 закрывает операторский UX/operations gap trainer: отдельное окно показывает heartbeat, фазу, wait reason, data-readiness и последние результаты, а authenticated PostgreSQL-backed commands позволяют немедленно повторить scheduler check либо запустить ограниченный recovery без выполнения обучения в API и без обхода model gates.
Версия 1.8.1 закрывает crash-recovery gap этой очереди: stale `RUNNING` request больше не блокирует enqueue навсегда. Система требует одновременно истекший пяти-минутный claim window и stale/missing heartbeat владельца, фиксирует прежнюю попытку как `FAILED`, создает новый linked retry, пишет audit/outbox и отвергает late completion по claim-token.
Версия 1.8.7 закрывает четыре связанные fail-open ошибки контура принятия: entry-zone проверяется по исполнимому ask/bid вместо last price, read-only capital snapshot имеет строгий age/future-time gate, общий open risk читается и резервируется под глобальным transaction-scoped advisory lock, а стоп за оценочной liquidation boundary блокируется при любом плече.
Версия 1.8.8 закрывает десять математических и эконометрических boundary-дефектов: stateful features сбрасываются на разрывах и invalid OHLCV, label path валидируется, probabilities проверяются как TP/SL/TIMEOUT simplex во всех вычислительных слоях, directional policy требует парный LONG/SHORT контракт, holdout drawdown строится по modeled exit events, а невалидный exchange max leverage блокируется.
Версия 1.8.9 закрывает research/live parity gap: barrier dataset сохраняет cohort только при валидной паре LONG/SHORT, а temporal split, holdout policy и backtest независимо fail-closed проверяют точную directional cardinality.
Версия 1.8.10 исправляет связанный набор математических, эконометрических и lifecycle-дефектов: funding имеет trader-perspective знак для LONG/SHORT, все денежные/cost inputs и directional observations валидируются до ранжирования, class distributions и incumbent metrics fail-closed, runtime требует точный artifact contract и полный finite feature vector, adverse executable entry пересчитывает plan, а фактический риск ручной позиции хранится и уменьшается при partial close. PlanOutcome теперь оценивает конкретную immutable plan version по ее entry/planning time, а release manifest снова самопроверяем.
Версия 1.8.11 закрывает следующий quant-integrity слой: holdout policy больше не считает каждый перекрывающийся H-часовой сигнал полнокапитальной независимой ставкой, promotion gate требует точную policy-metric schema/horizon, TP/TIMEOUT/label-end metadata проверяются на математическую согласованность, funding execution-plan пересчитывается от фактического planning time, leverage не усекается до целого, outcome bars обязаны иметь точный interval и когерентный OHLC, а manual fills не могут быть future-dated.
Версия 1.8.12 закрывает open-gap integrity gap: barrier labels и counterfactual outcomes используют упорядоченный open раньше unordered high/low, adverse stop gap оценивается по наблюдаемой цене открытия, opening exit time не сдвигается к close, а realized policy/backtest/PlanOutcome уменьшают stop-gap reserve на уже реализованную ценой часть.

Версия 1.8.13 закрыла обнаруженную регрессию propagation: `chronological_split` в 1.8.12 удалял `exit_at_open` перед final holdout, после чего validator молча подставлял `False`. Поле стало обязательным, а contract был повышен до `exit-time-open-gap-propagated-horizon-sleeves-v4`, чтобы затронутые v3-метрики не участвовали в auto-activation comparison.

Версия 1.8.15 закрывает quote/plan-contract gap: crossed и non-finite bid/ask fail-closed блокируются в universe, signal, UI и accept; поврежденный ticker не обрывает batch; TP2 удален из executable guidance до реализации полноценной weighted partial-exit разметки, EV/R и outcome accounting.

Это по-прежнему не превращает проект в доказанную production-стратегию. Полный multi-fold walk-forward, исторический стакан, live drift-control, перенос intrabar semantics в training/backtest и forward evidence остаются отдельными этапами.

## Реализовано и приведено в соответствие

| Область | Статус | Реализация |
|---|---|---|
| FastAPI/Uvicorn и PostgreSQL во всех режимах | Реализовано | `app/main.py`, `app/db/*`, Alembic, validator PostgreSQL URL |
| Отдельный worker для ingestion/inference | Реализовано | `app/workers/runner.py`; длительные задачи не выполняются в HTTP request |
| Отдельный background trainer | Реализовано; UX усилен в 1.8.0, crash recovery в 1.8.1 | отдельный процесс, advisory lock, heartbeat/job history, fail-safe candidate lifecycle, операторское окно и восстанавливаемая PostgreSQL control queue |
| Advisory-only, без отправки ордеров | Реализовано | Bybit-клиент использует public/read-only GET; ручные решения и fills сохраняются отдельно |
| Хронология ручного исполнения | Исправлено в 1.7.12 | manual-close валидирует entry/latest fill time под row lock до изменения qty, P&L, audit и outbox |
| Market signal отдельно от execution plan | Реализовано | `MarketSignal`, versioned `ExecutionPlan`, профили капитала |
| Cost-aware R/R, EV и sizing | Реализовано | комиссии, slippage, stop reserve, funding scenario, min-order/margin/liquidity/portfolio caps |
| Funding/cost sign and numeric boundary | Усилено в 1.8.11 | положительный funding: LONG платит, SHORT получает; execution plan повторно проецирует settlements от planning time; ненулевой settlement с неизвестным interval блокируется; отрицательные/non-finite costs fail-closed |
| Actual manual-position open risk | Исправлено в 1.8.10 | actual entry/qty определяют `initial_stress_loss`; `remaining_stress_loss` уменьшается пропорционально partial close и участвует в portfolio cap |
| Adverse executable-entry revalidation | Исправлено в 1.8.10 | future ticker/spec отвергаются; ухудшившийся ask/bid создает новую plan version с повторным sizing, net R/R, EV и liquidation checks |
| Probability simplex boundary | Исправлено в 1.8.8 | runtime artifact, Decimal EV/R, holdout policy и research backtest требуют finite TP/SL/TIMEOUT probabilities в `[0,1]` с суммой 1 |
| Directional cohort integrity research/live | Исправлено в 1.8.9 | dataset атомарно формирует `LONG + SHORT`; split, holdout и backtest отвергают missing/duplicate/unknown direction до policy metrics |
| Acceptance execution/risk revalidation | Исправлено в 1.8.7 | ask для LONG/bid для SHORT, fresh account snapshot, global PostgreSQL advisory lock до open-risk check, stop beyond liquidation fail-closed |
| Directional geometry fail-closed | Исправлено в 1.7.4 | единый validator LONG/SHORT для risk, sizing и outcome; invalid plan получает `BLOCKED_INVALID_INPUT` и нулевой размер |
| Numeric sizing inputs fail-closed | Исправлено в 1.7.5 | finite/positive capital, risk and instrument constraints; finite non-negative costs/margin/caps; invalid values дают zero-sized `BLOCKED_INVALID_INPUT` |
| Counterfactual plan inputs fail-closed | Исправлено в 1.7.6 | finite qty/prices/stress loss/costs/funding; malformed plan snapshot дает terminal zero-valued `INVALID_INPUT`, audit diagnostic и per-plan isolation |
| Компактная плитка, подробный диалог и glossary | Реализовано | HTML/CSS/Vanilla JS, keyboard/touch/hover подсказки, modal actions |
| Наблюдаемость и безопасное управление trainer | Реализовано в 1.8.0; stale-claim recovery в 1.8.1 | modal heartbeat/phase/wait/progress/result; authenticated `CHECK_NOW`/`RECOVER_NOW`; abandoned claim получает terminal evidence, linked retry и late-completion guard; API не выполняет fitting и не ослабляет gates |
| Один текущий сигнал на символ | Реализовано | supersede-логика и частичный уникальный индекс PostgreSQL |
| ML-задача TP/SL/TIMEOUT, а не NO TRADE | Исправлено в 1.3.0 | direction-conditional barrier dataset и трехклассовая модель |
| Временная калибровка | Исправлено в 1.3.0 | отдельное более позднее calibration window, sigmoid OVR |
| Final holdout и purge gap | Реализовано частично; усилено в 1.7.10 | единичный chronological train/calibration/final-holdout split; overlap очищается по `label_end_time` и embargo, multi-fold walk-forward отсутствует |
| Непрерывность hourly feature/label windows | Исправлено в 1.7.11; state reset усилен в 1.8.8 | live snapshot требует 24 последовательных валидных часов; gap/duplicate/invalid OHLCV сбрасывает EMA/ATR/rolling state; label path валидируется и сохраняет diagnostics |
| Model registry и воспроизводимый артефакт | Реализовано | SHA256, feature/task/horizon validation, activation/rollback, одна active-модель |
| Exact artifact/runtime contract | Усилено в 1.8.10 | exact feature schema version, positive integer horizon, non-empty calibration version, expected classes and complete finite runtime features; zero-imputation отсутствующих признаков запрещена |
| Fail-closed promotion metrics | Усилено в 1.8.14 | exact finite class distribution и incumbent metrics; policy metadata обязана содержать boolean `exit_at_open`; metrics имеют `exit-time-open-gap-propagated-cohort-weighted-v5`, horizon/sleeves равны artifact horizon; v3/legacy comparison блокируется |
| Реальный runtime active-модели | Реализовано | worker загружает registry-active artifact и обновляет его без перезапуска |
| Fail-closed для обязательных входов inference | Реализовано | stale candle/ticker, missing features, bid/ask/spec и excessive spread блокируют публикацию |
| Point-in-time cutoff при inference | Реализовано | `close_time <= cutoff`, `available_at <= cutoff`, spec `valid_from <= cutoff` |
| Фоновое переобучение и auto-activation | Реализовано с 1.4.0 | rolling window, immutable candidates, same-holdout comparison, guarded atomic activation |
| Dataset-aware retraining | Реализовано в 1.5.0 | profile rows/timestamps/symbols/coverage; triggers по backfill и universe change |
| Фактическое накопление глубокой истории | Реализовано в 1.5.0 | progressive `history_backfill` до target days с batch/page limits и учетом launch time |
| Экономический gate auto-activation | Реализовано в 1.5.0; exit-time accounting исправлен в 1.8.8 | policy trades, realized mean/total R, profit factor и drawdown считаются по modeled exit events; incumbent-relative limits сохранены |
| JSON-safe candidate registration | Исправлено в 1.7.1 | internal fail-closed sentinels не сериализуются; non-finite metrics → `null`; registry/job/audit JSONB защищены |
| Recovery после утраты active artifact | Реализовано в 1.7.2–1.7.3 | explicit non-production baseline fallback, DEGRADED diagnostics, immediate bootstrap/recovery trigger after startup delay, short technical retry backoff, strict integrity boundary и absolute gates |
| Orphan artifact reconciliation | Реализовано в 1.7.7 | status/UI inventory, explicit non-production recovery inside `MODEL_DIR`, metadata validation, absolute quality gate, guarded registry activation; directory presence alone не активирует model |
| Актуальный universe в UI/API | Исправлено в 1.5.0 | текущие карточки фильтруются по worker universe; status обновляется автоматически |
| Counterfactual outcome journal | Реализовано с intrabar refinement в 1.7.0 | confirmed hourly path; точечный 1/3/5-minute reconstruction для same-hour TP1/SL; отдельная оценка каждой plan version, audit/outbox/API/UI; missing intrabar и legacy funding timeline fail-closed |
| Plan-version valuation semantics | Исправлено в 1.8.10 | counterfactual P&L и funding settlements используют immutable plan `entry_price`/`planning_time`, а не исходные signal values после пересчета plan |

- Release boundary проверяется отдельным fail-closed manifest tool: missing/modified/unlisted files и запрещенные артефакты блокируют упаковку; это не меняет статус research gaps.

## Частичное соответствие

| Требование | Что есть | Чего не хватает |
|---|---|---|
| Walk-forward OOS | temporal split, purge, final holdout | expanding/rolling многооконный pipeline, OOF aggregation, embargo как отдельная сущность |
| Event-driven backtest | barrier outcomes, EV/R policy, exit-notional fees, H capital sleeves, active-position concurrency, cost reserve | entry-zone/no-fill, partial fills, intrahorizon mark-to-market, реальная funding timeline, dynamic correlation-aware portfolio, operator latency |
| Multi-horizon 4/8/12 | артефакт хранит horizon; можно обучить отдельные версии | одновременное сравнение нескольких горизонтов в live policy и отдельные active heads |
| Point-in-time universe research | live universe, candles, dataset profiles | исторические membership snapshots, delisted contracts и полностью point-in-time research universe |
| Liquidity/impact | spread и turnover-based caps | архив orderbook snapshots, depth VWAP и эмпирическая impact-модель |
| Fees | настраиваемая taker fee | автоматическое использование account fee-rate snapshot в обучении/backtest и live расчетах |
| Portfolio risk | общий риск, single-name/directional ограничения | устойчивые correlation clusters и factor/beta exposure |
| Надежность модели в UI | вероятности, version/calibration, training profile и причины | calibration bin, OOS analog count, confidence interval, regime statistics, live drift status |
| Автоматическая эксплуатационная защита | pre-activation ML/policy gate, сохранение incumbent | live realized-performance gate и автоматический rollback после production degradation |

| Единая top-of-book валидация | Исправлено в 1.8.15 | finite positive `bid <= ask` используется в universe, signal policy, UI entry-state и accept/revalidation |
| Weighted partial-exit economics | Не реализовано; безопасно деактивировано в 1.8.15 | API публикует только TP1 с весом 100%; TP2 нельзя возвращать до согласования labels, probabilities, EV/R, sizing и outcome valuation |

## Не реализовано

- систематический PSI/feature/probability/calibration drift monitoring и автоматический fallback;
- полноценные feature registry, immutable dataset snapshots и fold-level experiment registry;
- единая 1–5-минутная разметка для training/backtest; post-event journal уже уточняет hourly ambiguity, но обучающие labels пока используют консервативное hourly правило;
- Probability of Backtest Overfitting и Deflated Sharpe Ratio;
- историческая модель фактического исполнения по стакану;
- завершенный paper/shadow forward evidence и доказательство экономического преимущества.

## Состояние машинного обучения и post-event журнала после коррекции 1.7.11

Технический ML-путь работает end-to-end:

1. Из confirmed hourly candles строятся два условных сценария на timestamp: LONG и SHORT; timestamp допускается только при полном непрерывном 24h feature-lookback и непрерывном будущем label-horizon.
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
