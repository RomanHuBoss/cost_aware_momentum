# Incident Runbook

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
