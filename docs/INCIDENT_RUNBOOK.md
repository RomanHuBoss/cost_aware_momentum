# Incident Runbook

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
