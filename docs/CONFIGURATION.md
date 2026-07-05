# Configuration

## Historical funding replay

Release 1.12.0 не добавляет новую `.env` переменную. Progressive funding backfill использует существующие `HISTORY_BACKFILL_ENABLED`, `HISTORY_BACKFILL_TARGET_DAYS`, `HISTORY_BACKFILL_INTERVAL_SECONDS`, `HISTORY_BACKFILL_SYMBOLS_PER_CYCLE`, `HISTORY_BACKFILL_PAGES_PER_SYMBOL` и `HISTORY_BACKFILL_PAGE_SIZE`. Для funding endpoint effective page size ограничивается 200.

Training требует фактическую settlement timeline на всём исследуемом интервале и один anchor event не позднее entry. При гэпе cohort исключается; если пригодных labels не осталось, candidate не создаётся. После увеличения target history дождитесь завершения funding и candle backfill до retraining.

`--funding-rate` в research backtest является только дополнительным adverse ex-ante stress. Он не заменяет и не изменяет realized historical settlement cash flows.

## Walk-forward validation

Release 1.11.0 не добавляет новую `.env` переменную. Safety protocol зафиксирован в code/artifact contract:

- 3 expanding folds;
- fresh training and calibration per fold;
- purge/embargo равен model horizon;
- минимум 90 LONG/SHORT rows в каждом fold test;
- positive ML skill и positive policy mean R минимум в 2 из 3 folds.

Значения намеренно не являются операторским tuning knob: изменение числа folds или stability threshold требует новой schema, тестов и model governance review.

## MODEL_ENTRY_SPREAD_BPS

`MODEL_ENTRY_SPREAD_BPS` — конечное неотрицательное число, представляющее полный historical bid/ask spread stress в basis points.

Default:

```env
MODEL_ENTRY_SPREAD_BPS=18
```

Для hourly open proxy `O`:

- LONG entry = `O * (1 + spread_bps / 20000)`;
- SHORT entry = `O * (1 - spread_bps / 20000)`.

Переменная влияет на labels, TP/SL barriers, timeout return и policy backtest. Изменение требует нового обучения. Candidate, обученный с другим spread, не сравнивается с incumbent как эконометрически совместимый.

## Что параметр не покрывает

Параметр не заменяет historical quotes/orderbook и не оценивает depth, queue position, VWAP impact, no-fill, partial-fill или задержку оператора.
