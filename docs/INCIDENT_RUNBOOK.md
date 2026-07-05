# Incident Runbook

## Симптом: production drift status `BLOCKED`

Проверьте `alerts`, число hourly inference jobs, `failed_inference_jobs`, coverage, feature/probability observations и resolved outcomes. `active_artifact_model_required` означает baseline/отсутствие активного artifact; `invalid_production_drift_reference` — legacy или повреждённый artifact; `failed_inference_jobs_in_window` нельзя устранять исключением failed rows из отчёта. Исправьте worker/data flow или переобучите artifact, не переводите monitor в fail-open.

## Симптом: `feature_distribution_drift` / `probability_distribution_drift`

Сравните drift по отдельным признакам/классам, missingness, model version, universe composition и market regime. PSI использует фиксированные final-holdout bins; не пересчитывайте bins на production окне. Проверьте также schema/feature order и live context availability до изменения thresholds.

## Симптом: `calibration_drift`

Убедитесь, что накоплено достаточно resolved `SignalOutcome`, outcome resolver работает, а сравнение относится к той же active model version. Calibration baseline и production используют selected direction; смешивание counterfactual LONG/SHORT rows запрещено. Не интерпретируйте задержку outcome как отсутствие drift.

## Симптом: `actionability_density_drift`

Проверьте RR/EV thresholds, fees/slippage/funding inputs, spread/orderbook regime и universe. Изменение плотности рекомендаций может быть экономически нормальным, но требует анализа; monitor не меняет policy автоматически.

## Симптом: heartbeat `DEGRADED`, но модель продолжает работать

Это ожидаемо: drift monitor является diagnostic alert gate. Поле `automatic_model_action=none` запрещает скрытую деактивацию/rollback. Оператор должен сохранить evidence, проверить data quality, paper/shadow результаты и только затем принять явное governance-решение.

## Симптом: `incomplete_market_context` / рекомендации исчезли после 1.16.0

Проверьте, что `UNIVERSE_SYNC_MARK_PRICE=true` и `UNIVERSE_ENRICH_FUNDING_OI=true`, worker успешно сохраняет current `price_type=mark/index`, hourly OI и funding, а `available_at` не позже inference cutoff. Сравните exact `event_time/close_time` с decision boundary. Не подставляйте нули, stale OI или last price вместо mark/index.

## Симптом: training исключает много timestamps из-за market context

Проверьте `history_backfill.index_price_history`, `open_interest_history` и `funding_history`: earliest/newest, hourly continuity, duplicates, positive OI, valid funding interval и API errors. Для первых 24 часов каждого symbol OI-24h feature закономерно недоступен. Увеличьте фактическое покрытие, а не ослабляйте completeness.

## Симптом: `invalid_market_context_*` / artifact не загружается

Artifact создан до 1.16.0, повреждён или не содержит exact context/availability/ablation schemas. Сохраните его для аудита, завершите backfill и переобучите. Не редактируйте joblib вручную.

## Симптом: `market_context_ablation_regression` или `market_context_walk_forward_instability`

Context model ухудшает final holdout более допустимых 0.005 log loss либо нестабилен более чем в одном walk-forward fold. Это валидный research failure. Не увеличивайте tolerance только ради activation; исследуйте data alignment, regimes, scaling и feature definitions, затем повторите эксперимент на новых данных.

## Симптом: selection report возвращает `LEDGER_INTEGRITY_ERROR`

Не редактируйте JSONB или hash вручную. Сохраните plan IDs из отчёта, проверьте audit chain, миграцию `0011_selection_experiment`, версию приложения и несанкционированные DB updates. Повреждённые строки исключать молча нельзя.

## Симптом: `CLASS_COLLAPSE` / `INSUFFICIENT_SAMPLE`

Это означает слишком мало ACCEPT или непринятых eligible plans. Не снижайте thresholds только ради IPSW. Используйте all-eligible и selected/unselected descriptive counts, продолжайте prospective paper/shadow накопление.

## Симптом: `POOR_OVERLAP` / `LOW_EFFECTIVE_SAMPLE_SIZE`

Оператор выбирает область признаков, почти не представленную среди непринятых планов, либо веса концентрируются на нескольких наблюдениях. Corrected mean намеренно отсутствует. Исследуйте правила отбора, дубли plan versions и стабильность eligibility; не интерпретируйте selected-only mean как policy edge.

## Симптом: все планы стали `BLOCKED_STALE_DATA` после 1.14.0

Проверьте, что migration head равен `0010_orderbook_exec_evidence`, worker выполняет `market_sync`, а `orderbooks.failed` не растёт. Сравните exchange `source_time`, local `received_at` и `MAX_ORDERBOOK_AGE_SECONDS`. Не увеличивайте stale threshold только ради появления планов; сначала устраните сетевую задержку, API errors, неверное системное время или слишком длинный market cycle.

## Симптом: `BLOCKED_LIQUIDITY` / current orderbook cannot fully fill

Плановая qty не помещается в доступную bid/ask depth внутри `MAX_VWAP_IMPACT_BPS`. Не округляйте qty вверх и не заменяйте VWAP best quote. Уменьшите капитал/risk policy, дождитесь нового snapshot либо осознанно измените impact policy с последующим пересчётом plan.

## Симптом: legacy plan требует recalculation

Execution plan создан до `bybit-rest-depth-vwap-fill-v1`, его evidence повреждено или qty/VWAP не совпадают. Это ожидаемое fail-closed поведение. Используйте возвращённый `new_plan_id`; не редактируйте `sizing_snapshot` вручную.

## Симптом: `orderbooks.failed` растёт

Проверьте public Bybit connectivity, response type, symbol eligibility, timestamps, sorted levels и crossed-book diagnostics. При большом dynamic universe сравните duration `market_sync` с `MARKET_POLL_SECONDS`. Не добавляйте unbounded concurrency и не отключайте validation.

## Симптом: таблица orderbook быстро растёт

Проверьте `ORDERBOOK_DEPTH_LEVELS`, число активных symbols, `MARKET_POLL_SECONDS`, `ORDERBOOK_RETENTION_HOURS` и успешность hourly `market_snapshot_retention`. Уменьшение retention допустимо после оценки audit requirements; удаление свежего evidence перед разбором инцидента нежелательно.

## Симптом: active artifact не загружается после 1.13.0

Вероятная причина: artifact создан до `bybit-mark-price-hourly-isolated-margin-proxy-v1`, metadata отсутствует/повреждена либо leverage/reserve не совпадает. Не редактируйте joblib вручную. Сохраните artifact для аудита, завершите mark-price backfill, подтвердите `DEFAULT_LEVERAGE`, переобучите candidate и активируйте только artifact с корректным SHA-256 и complete margin-path schema.

## Симптом: training исключает много cohort из-за mark timeline

Проверьте `history_backfill.mark_price_history`: symbol, earliest/newest timestamp, exact hourly continuity, `price_type=mark`, confirmed status и OHLC validity. Нельзя подставлять last-price candles вместо mark candles или интерполировать missing bars без отдельной audited policy.

## Симптом: `invalid_intrahorizon_margin_schema` / `intrahorizon_margin_path_incomplete`

Candidate не содержит обязательное evidence либо оно повреждено. Повторите backfill/training. Не отключайте runtime/gate validation и не понижайте reason severity.

## Симптом: `intrahorizon_research_leverage_mismatch` или reserve mismatch

Candidate создан при других margin assumptions. Верните соответствующий `DEFAULT_LEVERAGE` либо переобучите candidate. Сравнивать candidate и incumbent с разной margin geometry запрещено.

## Симптом: liquidation rate резко вырос

Сначала проверьте mark data quality, leverage, funding timing и отсутствие duplicate/gap. Затем исследуйте режим рынка. Не называйте proxy событие точной исторической ликвидацией: hourly OHLC и fixed reserve дают консервативную, но неполную геометрию.

## Симптом: active artifact не загружается после 1.12.0

Вероятная причина: artifact создан до `bybit-settlement-timestamp-replay-v1` либо timeline metadata отсутствует/повреждена. Не редактируйте joblib вручную. Сохраните artifact для аудита, завершите funding backfill, переобучите candidate и активируйте только artifact с корректным SHA-256 и funding schema.

## Симптом: training не строит labels после обновления

Проверьте `history_backfill.funding_history.progress`: anchor до entry, earliest/newest settlement, instrument funding interval и ошибки Bybit response. Пропущенный ожидаемый settlement блокирует cohort намеренно. Не подставляйте нулевую ставку и не отключайте completeness check.

## Симптом: `policy_expected_funding_lookahead_risk`

Candidate metrics заявляют использование будущего actual funding в ex-ante policy. Такой candidate запрещён к activation. Исправьте research pipeline и переобучите модель; не меняйте reason severity.

## Симптом: active artifact не загружается после 1.11.0

Вероятная причина: artifact создан до введения `final-holdout-plus-expanding-walk-forward-v4` либо не содержит `walk_forward_schema`.

1. Не ослабляйте runtime validation и не редактируйте joblib вручную.
2. Сохраните старый artifact для аудита.
3. Проверьте достаточность исторических hourly timestamps.
4. Запустите trainer для создания нового candidate.
5. Активируйте только artifact с корректными SHA-256, temporal и walk-forward schemas.

## Симптом: `incomplete_walk_forward_validation` или `invalid_walk_forward_evidence`

Проверьте число folds, временной порядок test windows, row counts и целостность candidate metrics. Такое состояние может означать недостаточную историю, class collapse, ошибку training или повреждение artifact. Candidate не должен активироваться.

## Симптом: `walk_forward_*_above_limit` или `walk_forward_*_stability_below_minimum`

Это подтверждение временной нестабильности, а не техническая причина снизить thresholds. Сохраните experiment evidence, исследуйте regimes/data quality/features и дождитесь новых данных. Не подменяйте walk-forward одним удачным final holdout.

## Симптом: `entry_spread_bps_mismatch`

Candidate был рассчитан при другой execution configuration. Не редактируйте artifact. Верните конфигурацию, использованную при training, либо переобучите candidate.

## Симптом: рекомендаций стало меньше

Более строгая temporal validation может не допустить auto-activation модели, проходившей один holdout. Это ожидаемое fail-closed поведение. Paper/shadow evidence и текущий incumbent должны сохраняться.
