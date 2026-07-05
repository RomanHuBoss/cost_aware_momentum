# Changelog

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
