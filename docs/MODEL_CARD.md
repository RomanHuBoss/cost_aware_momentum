# Model Card

## Назначение

Direction-conditional оценка исходов `TP / SL / TIMEOUT` для LONG и SHORT сценариев. `NO TRADE` остаётся policy decision, а не классом модели.

## Данные и время

Features строятся только по confirmed hourly candles. Decision-time и label-end semantics разделены; temporal split purged по фактическому label horizon. Inference разделяет market cutoff и availability cutoff. Вероятности относятся к точным ATR-барьерам обучающей задачи: runtime использует фактический `atr_pct_14` без скрытого clipping.

По умолчанию crypto model domain исключает известные Bybit TradFi `symbolType`: `stock`, `forex`, `commodity`, `xstocks` и `xstock`. Их явное включение конфигурацией не доказывает совместимость текущих features, labels, cost assumptions или risk policy и требует отдельной model validation.

## Runtime и policy safety

Deterministic baseline не является калиброванной моделью исходов. Он допускается для bootstrap/диагностики, но при `ALLOW_BASELINE_ACTIONABLE=false` любой его execution plan получает `NO_TRADE`, а принятие ранее сохранённого actionable-плана блокируется повторно. Это предотвращает прохождение EV/RR gate только из-за высокой ATR при нейтральных baseline probabilities.

TIMEOUT gross return является явной policy assumption `TIMEOUT_GROSS_RETURN_RATE`; она применяется одинаково в signal selection, plan/acceptance economics, API serialization, promotion evaluation и backtest default и сохраняется в immutable snapshots. Default `-0.002` — консервативная гипотеза, а не установленная рыночная константа.

## Activation

Candidate artifact immutable, снабжается hash/metadata и сравнивается с incumbent только на совместимом final holdout с одинаковыми horizon, feature schema, label-path schema, temporal-split schema и ATR barrier geometry. Auto-activation допускается только после absolute и relative ML/policy gates. При включенной auto-activation абсолютный порог realized mean R не может быть отрицательным, а минимальный profit factor не может быть ниже 1. Profit factor использует отдельные weighted trade contributions: прибыль и убыток с одинаковым exit timestamp не взаимопогашаются. Он считается неограниченным только при явно положительном gross gain и нулевом gross loss; missing/no-trade данные не получают такой трактовки. Минимальные raw trades и независимые decision-time cohorts задаются раздельно (`AUTO_TRAIN_MIN_POLICY_TRADES`, `AUTO_TRAIN_MIN_POLICY_COHORTS`). Независимая когорта выбирается только после истечения полного label horizon предыдущей выбранной когорты; соседние часовые labels не считаются независимыми. Final holdout дополнительно обязан покрывать `AUTO_TRAIN_MIN_HOLDOUT_SPAN_HOURS` (default 168). Текущая policy metric schema — `exit-time-open-gap-horizon-independent-cohort-v8`. Перед расчётом policy evidence перекрывающиеся кандидаты одного symbol исключаются до modeled exit предыдущей позиции, как это делает live acceptance; количество блокировок сохраняется в `policy_overlap_blocked_trades`. Evidence схем v7 и ниже не проходит promotion gate и должно быть пересчитано текущим trainer. После quality-gate rejection trainer ждёт новых timestamps или material data-profile change вместо повторения детерминированного обучения на тех же данных. Ошибка candidate не деактивирует incumbent.

## Ограничения

Текущий research layer не воспроизводит полностью исторические order book, fills и точную funding timeline для каждого outcome. План, созданный позже signal anchor, не получает денежную контрфактическую оценку без entry-aligned path и помечается `PATH_UNAVAILABLE`. Полный walk-forward, drift/regime governance и PBO/DSR не завершены.

Зелёные тесты и корректная реализация не доказывают устойчивую доходность. Необходимы OOS/forward evidence и реалистичная оценка исполнения.
