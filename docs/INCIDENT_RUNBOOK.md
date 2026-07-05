# Incident Runbook

## Симптом: active artifact не загружается после 1.10.0

Вероятная причина: artifact создан со старой frictionless-open label schema или не содержит execution metadata.

1. Не ослабляйте runtime validation.
2. Сохраните incumbent artifact для аудита, но не активируйте вручную.
3. Проверьте `MODEL_ENTRY_SPREAD_BPS`.
4. Запустите trainer на достаточной истории.
5. Убедитесь, что candidate прошёл absolute и incumbent-relative gates.
6. Активируйте только artifact с новой schema и корректным SHA-256.

## Симптом: quality gate сообщает `entry_spread_bps_mismatch`

Candidate был рассчитан при другой execution configuration. Не редактируйте artifact. Верните конфигурацию, использованную при training, либо переобучите candidate.

## Симптом: рекомендаций стало меньше

Spread-aware labels могут уменьшить measured edge и policy density. Это ожидаемое fail-closed поведение, а не основание снижать risk/quality thresholds. Сначала исследуйте OOS results, data coverage и residual execution gaps.
