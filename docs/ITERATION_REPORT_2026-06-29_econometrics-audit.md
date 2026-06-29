# Аудит эконометрики и риск-математики — release 1.8.5

## 1. Объём проверки

Проверены утверждения внешнего эксперта по следующим путям:

- `scripts/backtest.py`;
- `app/ml/training.py`, `app/ml/runtime.py`, `app/ml/features.py`, `app/ml/labels.py`;
- `app/risk/math.py`;
- `app/services/signals.py`, `app/services/outcomes.py`;
- связанные unit tests и release-документация.

Целью было не механически принять замечания, а воспроизвести экономический смысл каждой формулы и проверить train / holdout / backtest / live consistency.

## 2. Итог по замечаниям эксперта

| № | Утверждение | Решение | Статус в 1.8.5 |
|---|---|---|---|
| 1 | Перекрывающиеся полногоризонтные returns ошибочно компаундятся каждый час | Подтверждено | Исправлено: `H` неперекрывающихся capital sleeves, PnL отражается в exit time |
| 2 | Backtest выбирает направление не по той policy, что production | Подтверждено | Исправлено: выбор по net `EV/R`, затем net RR и детерминированный tie-break |
| 3 | Backtest использует плоскую round-trip commission | Подтверждено | Исправлено: две равные fee legs на entry и фактический exit notional |
| 4 | Barrier multipliers захардкожены и могут дать train/serve skew | Подтверждено | Исправлено: runtime валидирует и передаёт multipliers из model bundle в live signal geometry |
| 5 | Funding boundary считает лишний settlement | Частично подтверждено | Исправлена граница старта: settlement ровно в `start_time` не считается. Settlement ровно в `end_time` остаётся включённым, если позиция удерживается до этой границы |
| 6 | Первый hourly bar содержит небольшой pre-publication участок | Ограничение данных подтверждено | Алгоритм не подменён ложной точностью. Без tick/actual fill path невозможно корректно отделить секунды до публикации внутри первого бара; риск явно оставлен в документации |
| 7 | Stop-gap reserve отражается как результат SL | Это осознанная conservative estimate, не actual fill PnL | Контракт outcomes сохранён; backtest дополнительно выводит return без stop-gap reserve для раздельной интерпретации |

## 3. Подтверждённый дефект: overlapping compounding

До исправления backtest группировал сделки по `decision_time`, усреднял полный return каждой сделки за весь label horizon и выполнял:

`cumprod(1 + hourly_cohort_return)`.

При горизонте 8 часов cohorts, открытые в соседние часы, одновременно находятся в рынке. Почасовое последовательное компаундирование полных 8-часовых returns неявно переиспользовало один и тот же капитал до закрытия предыдущей позиции. Это могло создавать экономический эквивалент многократного скрытого плеча и искажало как total return, так и drawdown.

### Исправление

Для горизонта `H` капитал делится на `H` равных sleeves. Hourly cohort использует sleeve, определяемый часовым слотом; тот же sleeve может быть повторно использован не раньше чем через `H` часов. Внутри cohort капитал равновзвешенно делится между символами. Доходность каждого sleeve компаундится только между неперекрывающимися cohorts. PnL отражается в modeled candle exit time, определяемый через `exit_index`.

Такой accounting:

- не создаёт H-кратное плечо;
- сохраняет допустимое компаундирование после освобождения капитала;
- корректно агрегирует одновременные символы;
- не выдаёт intrahorizon mark-to-market, которого нет в hourly labels.

Добавлен regression test: две перекрывающиеся двухчасовые сделки по +10% дают +10% портфелю, а не +21%.

## 4. Подтверждённый дефект: policy mismatch

До исправления backtest ранжировал LONG/SHORT по `predicted_net_edge`, то есть по ожидаемой чистой доходности в rate units. Production и holdout activation gate выбирают максимальный `EV/R`, где ожидаемый net rate нормируется на stress downside.

Эти ранжирования не эквивалентны. Сценарий с более высоким raw expected rate может иметь существенно худшую доходность на единицу риска.

### Исправление

Backtest теперь для каждого directional scenario рассчитывает:

- exit-notional-aware fees;
- net upside;
- stress downside;
- timeout net rate;
- net RR;
- expected net rate;
- expected `EV/R`.

На каждом `decision_time + symbol` выбирается максимальный `EV/R`; policy gate требует одновременно `net_rr >= minimum_net_rr` и `expected_ev_r >= minimum_net_ev_r`.

CLI `--minimum-predicted-edge` оставлен только как deprecated alias для `--minimum-net-ev-r`.

## 5. Подтверждённый дефект: commission normalization

До исправления из каждого realized return вычитался один плоский `round_trip_cost_bps / 10000`, как будто entry и exit notionals равны.

Корректная normalized fee при двух одинаковых fee legs:

`fee_per_leg * (1 + exit_price / entry_price)`.

Для LONG TP exit notional больше entry notional, поэтому старая формула занижала commission; для LONG SL — завышала. Для SHORT знак различия меняется через соответствующий exit ratio.

### Исправление

Backtest использует тот же контракт, что `normalized_round_trip_fee_rate`, `evaluate_policy_model` и counterfactual outcomes. Добавлен численный test: при LONG +10% и round-trip 1% комиссия равна 1.05%, net return — 8.95%.

## 6. Подтверждённый риск: artifact barrier geometry

Artifact сохраняет `stop_atr_multiplier` и `tp_atr_multiplier`, но live signal geometry использовала литералы `1.15` и `2.20`. При обучении на другой barrier geometry это создавало silent train/serve skew: вероятности относились к одним барьерам, а оператору публиковались другие.

### Исправление

`ModelRuntime`:

- загружает оба multiplier из bundle;
- проверяет, что они положительны и конечны;
- использует совместимые defaults для старых artifacts;
- публикует multipliers в runtime metadata;
- применяет их в compatibility utility score.

`publish_hourly_signals` передаёт multipliers в `select_cost_aware_scenario`, а live stop/TP1 строятся по artifact geometry.

TP2 и entry zone не являются primary model barriers и остаются отдельными policy constants.

## 7. Funding boundary

`projected_funding_rate` раньше включал settlement, совпадающий с `start_time`, тогда как ex-post `_funding_rate_for_holding_period` его исключал. Для позиции, создаваемой после signal decision, settlement ровно на старте уже не должен считаться будущим.

Условие advance изменено с `< start_time` на `<= start_time`.

Settlement ровно на `end_time` остаётся включённым. Это согласуется с ex-post contract: если hypothetical holding period заканчивается на settlement boundary, такой settlement считается пересечённым. Реальное биржевое начисление на точной границе зависит от фактического execution timing, которого research model не знает.

## 8. Дополнительно найденный дефект: concurrency metric

Старая `max_concurrent_trades` считала только число новых trades с одинаковым `decision_time`. При 8-часовом горизонте одна новая сделка каждый час давала максимум `1`, хотя одновременно могли быть открыты восемь позиций.

Метрика заменена event sweep по entry и modeled exit times. Exits на границе обрабатываются до новых entries на той же границе. `mean_concurrent_trades` теперь time-weighted по периодам, когда портфель имеет открытые позиции.

## 9. Замечания, которые не следует исправлять упрощённой формулой

### Первый bar после signal event

`event_time` выровнен по часовому cutoff, а `publish_time` обычно на несколько секунд или минут позже. Hourly high/low первого future bar теоретически может включить движение до публикации. Это interval-censoring / pre-entry contamination, а не утечка feature/label training.

Без tick history, фактического fill или заранее определённого следующего executable bar невозможно корректно разделить этот интервал. Простое смещение на следующий час потеряло бы до часа валидного пути и изменило horizon; использование бара, содержащего publish time, сохранило бы ту же проблему на меньшем интервале. Поэтому 1.8.5 не вводит псевдоточное исправление. Ограничение должно учитываться при интерпретации counterfactual journal и закрываться отдельным execution-data work package.

### Stop-gap reserve

`estimate_plan_outcome` явно является conservative counterfactual estimate, а не actual execution PnL. Reserve на SL соответствует stored sizing assumptions и сохраняет согласованность R-denominator. Удалять его из основного результата без фактических fills нельзя.

Чтобы аналитик мог отделить reserve effect, backtest теперь дополнительно возвращает `net_return_without_stop_gap_reserve`. Actual manual fills по-прежнему должны анализироваться отдельно.

## 10. Проверки

После изменений:

- `python -m compileall -q app scripts tests manage.py` — PASSED;
- `python -m ruff check .` — PASSED;
- `python -m pytest -q -rs` — `169 passed, 4 skipped`;
- четыре skip — PostgreSQL integration tests, потому что `TEST_DATABASE_URL` не настроен;
- schema migration не требуется;
- artifact retraining не требуется;
- старые artifacts без multiplier fields остаются совместимыми через defaults.

## 11. Остаточные ограничения

Исправленный research backtest всё ещё не является полным execution simulator. Не моделируются:

- historical order book, spread path и market impact;
- entry-zone/no-fill и partial fills;
- actual funding history по каждому symbol/time;
- intrahorizon mark-to-market и liquidation path;
- operator latency и фактическое время ручного входа;
- cross-symbol correlation-aware dynamic capital allocation.

Эти ограничения влияют на переносимость результата в live и должны оставаться частью go/no-go оценки.
