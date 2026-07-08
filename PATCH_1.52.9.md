# Patch 1.52.9 — Trainer wait progress clarity

Дата: 2026-07-08.

## Problem

На чистой базе после первой bootstrap/recovery попытки оператор мог видеть `baseline-momentum-v1`, `quality_gate_failed_waiting_for_new_data`, progress `Новые размеченные часы: 6 из 168` и статус `SUCCESS`. Это состояние безопасно и ожидаемо, но UI не пояснял явно, что trainer не завис: previous candidate не прошёл quality gate, incumbent/baseline остаётся активным, а повтор до накопления новых label-eligible timestamps обычно не даст нового evidence.

## Solution

- Текст ожидания `quality_gate_failed_waiting_for_new_data` теперь прямо называет это штатным защитным ожиданием и уточняет, что active model не отключается и повтор без новых данных не запускается.
- Текст `training_deferred_waiting_for_new_data` аналогично объясняет, что temporal validation и quality gate не ослабляются.
- `trainerProgressRow()` показывает остаток до threshold: `6 из 168 · осталось 162` или `порог достигнут`.
- Для data-dependent trainer waits добавлена строка `Минимум до повтора`, чтобы оператор видел конкретный remaining threshold.

## Compatibility

- Миграций БД нет.
- Новых `.env` variables нет.
- API schema, model artifact schema, worker/trainer scheduling, quality gates, risk math и Bybit read-only boundary не менялись.
- После обновления достаточно перезапустить API/UI process; worker/trainer можно не перезапускать ради этого frontend-only patch, но общий rolling restart допустим.

## Verification

- Red evidence: новый regression test `test_operator_ui_explains_labeled_hour_wait_as_progress_not_failure` падал на 1.52.8, потому что UI не содержал `осталось`, `штатное защитное ожидание` и `Минимум до повтора`.
- Green evidence: `python -m pytest -q tests/unit/test_trainer_operator_ui.py` → `2 passed`.
- `node --check web/js/app.js` → passed.
- `python -m compileall -q app scripts tests manage.py` → passed.
- Full `pytest -q` в текущем shared sandbox не выполнен до collection из-за отсутствующего declared dependency `psycopg`; это environment limitation, зафиксированное в QA report.

## Limitations

Изменение улучшает операторскую диагностику и не доказывает economic edge стратегии. Если счётчик новых размеченных часов перестаёт расти несколько часов подряд, отдельно проверяйте ingestion/backfill/market-context coverage в PostgreSQL.
