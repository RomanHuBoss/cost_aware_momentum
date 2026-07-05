# Configuration

## Release 1.17.0 — production drift monitoring

No database migration is required. Add or review the following settings:

```env
DRIFT_MONITOR_ENABLED=true
DRIFT_WINDOW_HOURS=168
DRIFT_MIN_FEATURE_OBSERVATIONS=48
DRIFT_MIN_OUTCOME_OBSERVATIONS=30
DRIFT_MIN_COVERAGE_RATE=0.80
DRIFT_MAX_MISSING_RATE=0.02
DRIFT_WARNING_PSI=0.10
DRIFT_CRITICAL_PSI=0.25
DRIFT_MAX_LOG_LOSS_DELTA=0.10
DRIFT_MAX_BRIER_DELTA=0.05
DRIFT_MAX_ACTIONABILITY_RATE_DELTA=0.20
```

`DRIFT_WINDOW_HOURS` must be at least 24. Coverage is the fraction of scoped universe opportunities represented by newly published or already-current signals in successful hourly inference jobs. Any failed inference job in the window blocks the report rather than being omitted from the denominator.

PSI thresholds apply independently to every feature and TP/SL/TIMEOUT probability component. Calibration deltas use only resolved outcomes for the production-selected direction and compare with the same selected-direction final-holdout cohort. Until `DRIFT_MIN_OUTCOME_OBSERVATIONS` is reached, calibration is reported as insufficient evidence rather than silently assumed healthy.

`DRIFT_MONITOR_ENABLED=false` yields a visible `BLOCKED` report. The monitor never changes the active model. Artifact 1.16.0 lacks the mandatory drift reference; complete retraining and activation of a 1.17.0 candidate are required.

## Release 1.16.0 — market-context features

Новых имён `.env` и migration нет. Однако active artifact теперь требует ongoing mark/index/funding/OI refresh, поэтому defaults и `.env.example` изменены на:

```env
UNIVERSE_SYNC_MARK_PRICE=true
UNIVERSE_ENRICH_FUNDING_OI=true
```

Существующий `.env` со значениями `false` необходимо изменить вручную. `HISTORY_BACKFILL_*` управляет progressive backfill last/mark/index candles, open interest и funding. Для OI effective page size ограничивается 200 согласно public endpoint contract.

После обновления дождитесь покрытия `index_price_history` и `open_interest_history`, затем переобучите candidate. Artifact 1.15.0 не содержит context feature/ablation contract и отклоняется runtime fail-closed. Historical public data позволяет replay по exchange timestamps, но не восстанавливает фактическое локальное receipt time прошлых лет.

## Release 1.15.0 — selection experiment reporting

Новых `.env` параметров нет. После migration `0011_selection_experiment` каждая новая plan version автоматически создаёт prospective ledger row.

Команды:

```bash
python manage.py selection-report -- --days 90
python manage.py report -- --hours 24 --selection-days 90
```

Минимальные sample/overlap/ESS thresholds зафиксированы в analysis contract и не должны снижаться ради получения числового результата. До накопления данных отчёт честно возвращает `INSUFFICIENT_SAMPLE`, `CLASS_COLLAPSE`, `NO_OUT_OF_SAMPLE_SCORES`, `POOR_OVERLAP` или `LOW_EFFECTIVE_SAMPLE_SIZE`.

## Release 1.14.0 — execution depth policy

| Variable | Default | Contract |
|---|---:|---|
| `ORDERBOOK_DEPTH_LEVELS` | `200` | Число bid/ask levels в public REST snapshot; допустимо 1..1000. |
| `MAX_ORDERBOOK_AGE_SECONDS` | `90` | Максимальный возраст и exchange source time, и local receipt time. Ноль/отрицательное значение запрещено. |
| `MAX_VWAP_IMPACT_BPS` | `12` | Максимальное неблагоприятное отклонение complete-fill VWAP band от best executable quote; должно быть конечным и неотрицательным. |
| `ORDERBOOK_RETENTION_HOURS` | `48` | Retention prospective snapshots; минимум 1 час. |

Изменение этих параметров не меняет market-model artifact и не требует retraining. Оно меняет account-dependent execution-plan semantics: существующие планы без `bybit-rest-depth-vwap-fill-v1` при принятии пересчитываются fail-closed. Перед запуском worker необходимо применить migration `0010_orderbook_exec_evidence`. Большой dynamic universe увеличивает число serial public REST requests и объём PostgreSQL; контролируйте market job duration и retention.

## Intrahorizon mark-price margin replay

Release 1.13.0 не добавляет новую `.env` переменную. Progressive mark-price backfill использует существующие `HISTORY_BACKFILL_*` параметры и сохраняет candles с `price_type=mark`. Training требует непрерывную hourly mark timeline на всём label path; гэп исключает LONG/SHORT cohort fail-closed.

Research leverage берётся из существующего `DEFAULT_LEVERAGE` (default `3`). Изменение `DEFAULT_LEVERAGE` меняет intrahorizon margin evidence и требует retraining. Fixed reserve `10%` initial margin не является tuning knob в `.env`: его изменение требует новой schema и model-governance review. Candidate и incumbent с разными leverage/reserve assumptions не сравниваются как совместимые.

Модуль не восстанавливает точные исторические MMR/risk tiers или cross margin. Поэтому `DEFAULT_LEVERAGE` здесь задаёт сценарий research isolated-margin proxy, а не обещание точного liquidation price биржи.

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
