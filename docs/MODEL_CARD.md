# Model Card

## Назначение

Direction-conditional оценка исходов `TP / SL / TIMEOUT` для LONG и SHORT сценариев. `NO TRADE` остаётся policy decision, а не классом модели.

## Данные и время

Features строятся только по confirmed hourly candles. Decision-time и label-end semantics разделены; temporal split purged по фактическому label horizon. Inference разделяет market cutoff и availability cutoff. Вероятности относятся к точным ATR-барьерам обучающей задачи: runtime использует фактический `atr_pct_14` без скрытого clipping.

По умолчанию crypto model domain исключает известные Bybit TradFi `symbolType`: `stock`, `forex`, `commodity`, `xstocks` и `xstock`. Их явное включение конфигурацией не доказывает совместимость текущих features, labels, cost assumptions или risk policy и требует отдельной model validation.

## Activation

Candidate artifact immutable, снабжается hash/metadata и сравнивается с incumbent только на совместимом final holdout с одинаковыми horizon, feature schema, label-path schema, temporal-split schema и ATR barrier geometry. Auto-activation допускается только после absolute и relative ML/policy gates. При включенной auto-activation абсолютный порог realized mean R не может быть отрицательным, а минимальный profit factor не может быть ниже 1. Profit factor использует отдельные weighted trade contributions: прибыль и убыток с одинаковым exit timestamp не взаимопогашаются. Он считается неограниченным только при явно положительном gross gain и нулевом gross loss; missing/no-trade данные не получают такой трактовки. Текущая policy metric schema — `exit-time-open-gap-propagated-cohort-weighted-v6`; v5 не проходит promotion gate. Ошибка candidate не деактивирует incumbent.

## Ограничения

Текущий research layer не воспроизводит полностью исторические order book, fills и точную funding timeline для каждого outcome. План, созданный позже signal anchor, не получает денежную контрфактическую оценку без entry-aligned path и помечается `PATH_UNAVAILABLE`. Полный walk-forward, drift/regime governance и PBO/DSR не завершены.

Зелёные тесты и корректная реализация не доказывают устойчивую доходность. Необходимы OOS/forward evidence и реалистичная оценка исполнения.
