# Configuration

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
