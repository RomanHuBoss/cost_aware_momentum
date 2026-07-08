# PATCH 1.52.4 — trainer data-dependent wait diagnostics

Дата: 2026-07-08.

## Problem

Операторский UI показывал:

```text
Действует защитная пауза после предыдущей попытки обучения.
Следующая допустимая попытка: ...
```

при активной `baseline-momentum-v1`. Код действительно защищал active incumbent и не запускал повторный trainer-loop слишком часто, но для rejected bootstrap/recovery candidate с `activation_skipped=quality_gate_failed` или data-dependent walk-forward deferral показывал generic cooldown до истечения 6 часов. Только после cooldown оператор видел настоящую причину: требуется material dataset change или минимум новых размеченных часов.

Отдельно fresh QA install с разрешённым старым constraint `numpy>=2.1,<3` подтягивал NumPy 2.5.1 и ломал существующие funding replay / policy phase unit contracts. С NumPy 2.3.5 suite проходит.

## Fix

- `BackgroundTrainer.due_reason()` теперь сначала проверяет data-dependent rejected bootstrap/recovery candidate на отсутствие новых данных.
- Если данных ещё недостаточно, heartbeat wait reason сразу становится `quality_gate_failed_waiting_for_new_data` или `training_deferred_waiting_for_new_data`.
- Wait reason включает previous skip code, last status/start time, required/new timestamps, dataset comparison и `next_due_at`, если cooldown window ещё не истёк.
- Generic cooldown остаётся для обычных failed/scheduled/data-change retries и для случаев, где нет profile evidence.
- UI добавил русские labels и progress bar для этих wait reasons.
- `pyproject.toml` ограничивает NumPy `<2.5` до отдельной совместимой адаптации под NumPy 2.5+.

## Compatibility

- Миграций БД нет.
- Новых `.env` variables нет.
- API contract, model-artifact schema и trainer quality thresholds не изменены.
- Cooldown limits не увеличены и не снижены.
- Fail-closed semantics сохранены: rejected candidate не активируется, baseline/incumbent остаётся действующим.

## Verification

Red on 1.52.3 with the new regression test:

```bash
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py::test_rejected_bootstrap_reports_new_data_wait_even_during_cooldown
# 1 failed: reason was training_cooldown_not_elapsed
```

Green after fix:

```bash
python -m pytest -q tests/unit/test_trainer_recovery_scheduling.py tests/unit/test_trainer_operator_ui.py
# 15 passed
```

Full post-check:

```bash
python -m pip check
python -m compileall -q app scripts tests manage.py
python -m ruff check .
python -m pytest -q
node --check web/js/app.js
alembic heads
```

Result: `858 passed, 8 skipped`; ruff/compile/node/alembic passed.

## Operational notes

- Перезапустите trainer и API/UI process.
- Если UI показывает `quality_gate_failed_waiting_for_new_data`, нажимать recovery до накопления новых данных обычно бесполезно: тот же candidate path снова упрётся в quality gate.
- Если после backfill появились новые размеченные часы или material dataset change, trainer автоматически попробует снова по штатному расписанию.
