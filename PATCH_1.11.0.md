# Patch 1.11.0 — purged expanding walk-forward validation

## Problem

До 1.11.0 candidate оценивался одним purged chronological train/calibration/final-holdout split. Такой split защищал одну границу от прямой temporal leakage, но не показывал, переживает ли ML skill и policy economics последовательные рыночные режимы. Один удачный holdout мог скрыть временную нестабильность.

## Solution

- Final holdout сохранён отдельным и не используется внутри development walk-forward.
- Development period разбит на три expanding-train / rolling-calibration / later-test fold.
- В каждом fold создаётся свежая model pipeline и отдельная calibration.
- Label overlap purged по `label_end_time`; применяется horizon embargo.
- Fold tests не перекрываются и сохраняются в artifact как проверяемое evidence.
- Auto-activation требует допустимого worst fold и положительного skill/policy mean минимум в 2 из 3 folds.
- Runtime требует новую temporal/walk-forward schema.

## Compatibility

- Database migration: нет.
- `.env`: новых переменных нет.
- Public API: без изменений.
- Artifact 1.10.0: несовместим с новым runtime contract, требуется retraining.
- Rollback: вернуть код 1.10.0 и соответствующий ему artifact; artifact 1.11.0 не считать совместимым со старым runtime.

## Verification

- Regression red: новый test module не импортировался, потому что `expanding_walk_forward_splits` отсутствовал.
- Green: новый module и gate regressions проходят.
- Full unit suite: 476 passed, 4 skipped.
- Ruff, compileall и Node syntax: passed.
- PostgreSQL integration: не выполнялась без отдельной test database.

## Limitations

Это не PBO, combinatorial purged CV, nested hyperparameter selection, production drift monitoring или доказательство прибыльности.
