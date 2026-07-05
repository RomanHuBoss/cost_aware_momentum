# Changelog

## 1.11.0 — 2026-07-05

### Добавлено

- Трёхфолдовый expanding walk-forward внутри development period с целыми decision timestamps, label-end purge и horizon embargo.
- Независимое переобучение и sigmoid calibration модели в каждом fold; final holdout не используется в walk-forward оценке.
- Fold-level evidence в immutable artifact: временные границы, row counts, log loss, prior skill, multiclass Brier и policy metrics.
- Fail-closed auto-activation gates для количества/порядка folds, временного перекрытия, худшего fold и устойчивости положительного ML skill и policy mean R.

### Изменено

- Temporal schema обновлена до `final-holdout-plus-expanding-walk-forward-v4`.
- Runtime требует `walk_forward_schema=expanding-train-rolling-calibration-purged-v1`.
- Минимальный объём истории теперь рассчитывается с учётом purged walk-forward windows; при текущих defaults требование остаётся 1206 hourly timestamps.

### Совместимость

- Миграция БД и новые `.env` переменные не требуются.
- Artifact 1.10.0 не содержит обязательную walk-forward schema и должен быть переобучен.
- Реализация не является PBO, nested cross-validation или доказательством прибыльности.

## 1.10.0 — 2026-07-05

### Исправлено

- Historical barrier labels больше не используют один frictionless `next-hour open` одновременно для LONG и SHORT. Entry proxy теперь direction-specific: LONG = open + half-spread, SHORT = open - half-spread.
- Первый label bar нормализуется к моменту моделируемого входа, чтобы движение до adverse spread entry не интерпретировалось как исполнимый TP/SL.
- Training, automatic trainer и research backtest используют единый `MODEL_ENTRY_SPREAD_BPS`.
- Artifact runtime и auto-activation gate fail-closed проверяют execution schema и spread value.
- Candidate/incumbent comparison пропускается при несовместимых entry spread/barrier semantics.

### Добавлено

- Конфигурация `MODEL_ENTRY_SPREAD_BPS` с default `18` bps.
- Regression tests для direction-specific entry, invalid configuration, artifact compatibility и quality-gate consistency.
- Документы архитектуры, конфигурации, QA, compliance, traceability, model card, security, runbook и operator manual, отсутствовавшие во входном release tree.

### Совместимость

- Миграция БД не требуется.
- Model artifacts с прежней label/execution schema несовместимы и должны быть переобучены.
