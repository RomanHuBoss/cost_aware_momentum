# Configuration

## Release 1.24.0 — candidate/live attrition diagnostics

No new environment variables or database migration are introduced. `python manage.py attrition-report -- --hours 168` controls the UTC lookback only through the CLI argument and writes `reports/candidate_live_attrition.json`. Existing model, policy, risk, drift and activation thresholds are unchanged. Instrumentation is prospective, so choose a post-upgrade window for an `OK` report.

## Release 1.21.0 — UI exposure coverage

Migration `0014_ui_exposure_ledger` is required. Add or confirm:

```env
SELECTION_MIN_EXPOSURE_COVERAGE=0.80
```

The value must be in `[0, 1]`. It is the minimum fraction of instrumented eligible opportunities with verified UI exposure required before an IPSW corrected estimate may be published. Lowering it does not create evidence; it only changes the report classification. Tile evidence itself uses fixed code-level safety bounds: at least 50% visibility, at least 1000 ms dwell, active document visibility, maximum 15-minute delivery age and maximum 5-second future clock skew.

No model artifact, feature schema, inference setting or risk parameter changes in this release.

## Release 1.20.0 — immutable experiment preregistration

No new `.env` variable is added. Migration `0013_experiment_preregistration` is required. Existing `EXPERIMENT_*` and `RESEARCH_*` values are used only to populate a new preregistration template. Once a family is registered, its report policy comes from the immutable JSON specification; command-line overrides are accepted only when they exactly match that specification.

A registration requires an explicit fixed/search partition of every backtest configuration key. `dataset_fingerprint`, `horizon`, configuration schema, policy source and portfolio accounting must be fixed. Search values are enumerated; undeclared parameters, values outside the list, expired deadlines and new variants after the maximum unique-configuration budget fail closed.


## Release 1.19.0 — dependence-aware research inference

```env
RESEARCH_BOOTSTRAP_REPLICATES=1000
RESEARCH_CONFIDENCE_LEVEL=0.95
EXPERIMENT_DEPENDENCE_BLOCK_PERIODS=8
EXPERIMENT_MIN_INDEPENDENT_BLOCKS=6
SELECTION_DEPENDENCE_BLOCK_CLUSTERS=5
SELECTION_MIN_INDEPENDENT_CLUSTERS=30
```

`RESEARCH_BOOTSTRAP_REPLICATES` must be at least 100 and `RESEARCH_CONFIDENCE_LEVEL` must be in `(0.5, 1)`. Experiment block periods and selection cluster-block length must be at least two. The minimum selection cluster count must cover at least two complete cluster blocks.

Experiment analysis uses `max(EXPERIMENT_DEPENDENCE_BLOCK_PERIODS, declared horizon)`. If the aligned return path cannot provide `EXPERIMENT_MIN_INDEPENDENT_BLOCKS`, the family report is blocked. Operator-selection inference requires at least `SELECTION_MIN_INDEPENDENT_CLUSTERS` among chronologically OOS-scored signals. These settings control reports only and never alter model fitting, signal publication, risk, execution plans or activation.

No migration and no model retraining are required. Expected Alembic head remains `0012_experiment_selection`.

## Release 1.18.0 — experiment-selection governance

```env
EXPERIMENT_PBO_SEGMENTS=6
EXPERIMENT_MIN_TRIALS=4
EXPERIMENT_MIN_PERIODS=60
EXPERIMENT_MAX_PBO=0.20
EXPERIMENT_MIN_DSR_PROBABILITY=0.95
```

`EXPERIMENT_PBO_SEGMENTS` must be an even integer of at least four. `EXPERIMENT_MIN_PERIODS` must support at least two observations per segment; minimum trials must be at least two. PBO/DSR thresholds are probabilities in `[0, 1]`. Invalid values stop settings validation.

These variables classify `experiment-report` output only. They do not affect feature generation, model fit, inference, model activation, execution plans or risk. Every comparable backtest must use one exact `experiment_family`; its successful variants must share an identical hourly return timestamp grid.

Migration `0012_experiment_selection` is required. No model retraining and no new exchange permission are required.

## Release 1.23.0 — maturity-aware drift calibration

No migration, new environment variable or threshold change is required. Existing `DRIFT_*` settings remain valid. After updating, restart the worker and regenerate `reports/production_drift.json`; its schema is now `production-drift-report-v2`.

Calibration observations are restricted to full-horizon mature signals (`event_time + horizon_hours <= report time`). Early TP/SL outcomes are disclosed but excluded. If any mature signal lacks its `SignalOutcome`, the report emits `incomplete_mature_outcome_coverage` and blocks calibration rather than evaluating a selected subset. `DRIFT_MIN_OUTCOME_OBSERVATIONS` is applied after this maturity and completeness filter.

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

PSI thresholds apply independently to every feature and TP/SL/TIMEOUT probability component. Calibration deltas use only complete, full-horizon mature outcomes for the production-selected direction and compare with the same selected-direction final-holdout cohort. Early resolved outcomes from immature signals are excluded to avoid right-censoring; unresolved mature signals block evidence. Until `DRIFT_MIN_OUTCOME_OBSERVATIONS` is reached after that filter, calibration is reported as insufficient evidence rather than silently assumed healthy.

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
