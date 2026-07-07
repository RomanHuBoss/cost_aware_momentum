# Patch 1.52.1 — fail-closed walk-forward deferral and contract diagnostics

Дата: 2026-07-08.

## Цель

Устранить подтверждённый incident path, при котором raw preflight history проходила minimum gate, но после feature/context/label filtering development dataset не мог построить три purged expanding walk-forward folds. Такое ожидаемое data-dependent состояние ошибочно завершало background job как `FAILED`, переводило trainer в `ERROR` и давало большой traceback. Одновременно decision-time execution warning терял все поля `extra` из-за ограниченного JSON formatter.

## Исправления

- Добавлен единый `WalkForwardCapacity` contract:
  - actual и required development timestamps;
  - folds и purge hours;
  - actual/minimum rolling block;
  - actual/minimum initial training region;
  - machine-readable reason code.
- Теоретический raw-history minimum и фактический splitter используют один расчёт minimum development capacity.
- `build_model_candidate()` проверяет post-filter development capacity до основного final model fit, если split предоставляет final holdout metadata.
- `expanding_walk_forward_splits()` поднимает специализированный `InsufficientWalkForwardHistoryError`, не ослабляя ни один temporal gate.
- Background trainer обрабатывает этот тип как ожидаемое fail-closed состояние:
  - PostgreSQL job остаётся технически успешно завершённым;
  - внутренний status — `DEFERRED`;
  - `activation_skipped` и `reason_code` фиксируют точную причину;
  - incumbent не изменяется;
  - heartbeat остаётся healthy/WAITING;
  - повторная попытка ждёт новых timestamps или material profile change.
- JSON formatter разрешает только специально перечисленные безопасные diagnostic fields.
- Decision-time execution warning теперь содержит `reason_code`, `contract_error`, event/publish time, lag и configured maximum delay.
- Mismatch error показывает artifact/runtime entry-zone и publication-delay values без секретов.

## Конфигурация и миграции

- Новых Alembic migrations нет.
- Новых `.env` variables нет.
- Существующие значения `DEFAULT_HORIZON_HOURS`, holdout, walk-forward folds и purge semantics не менялись.

## Совместимость

- Advisory-only и PostgreSQL-only boundaries сохранены.
- Existing active artifact не деактивируется и не перезаписывается.
- API schema не изменена.
- После обновления перезапустите inference worker и trainer, чтобы новый logging/deferral path применился.

## Ограничения

`DEFERRED` не означает, что модель станет валидной после фиксированного числа часов: gaps, missing context/spec/funding/mark data и symbol coverage могут продолжить сокращать post-filter dataset. Точное решение видно в `walk_forward_capacity`; gates намеренно остаются fail-closed.
