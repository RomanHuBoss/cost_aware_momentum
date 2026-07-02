# Patch 1.8.36 — decision-time entry integrity

## Проблема

Training dataset использовал close завершённой feature-свечи как entry, хотя признаки становятся доступны только в `decision_time`. Первая label-свеча могла открыться гэпом, и этот гэп записывался как TP/SL до момента, когда оператор или система вообще могли войти. В воспроизводимом LONG-примере close около 100 и следующий open 110 превращались в мгновенный TP `+0.01804`, хотя исполнимый вход был уже 110.

## Решение

- `make_barrier_dataset()` использует `future.iloc[0].open` как decision-time entry proxy.
- ATR distance рассчитывается от entry по сохранённому `atr_pct_14`, как в live policy.
- `entry_price` сохраняется в dataset/holdout metadata и проверяется fail-closed, когда присутствует.
- `LABEL_PATH_SCHEMA_VERSION` изменён на `decision-open-entry-ohlc-path-v2`.
- `POLICY_METRIC_SCHEMA` изменён на `decision-open-entry-exit-time-cohort-v9`.
- Runtime и quality gate не принимают старую семантику.

## Совместимость

- DB migration: отсутствует.
- Новые `.env` variables: отсутствуют.
- Старые model artifacts требуют штатного переобучения и повторной guarded activation.
- Старое policy evidence v8 и ниже требует пересчёта.
- Advisory-only, PostgreSQL-only, read-only Bybit и process boundaries не изменены.

## Проверки

- Baseline: 422 passed, 4 skipped, 19 warnings.
- Red: новый gap-entry regression test падал из-за отсутствующего `entry_price`; отдельная ATR-parity assertion показала 0.01640 вместо ожидаемых 0.01804.
- Green/post: 425 passed, 4 skipped, 19 warnings; Ruff, compileall, pip check, Node syntax и single Alembic head прошли.
- PostgreSQL integration не запускалась: отдельная безопасная test DB не предоставлена.
