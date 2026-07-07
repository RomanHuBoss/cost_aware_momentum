# Patch 1.52.0 — historical dynamic bootstrap with prospective upgrade

Дата: 2026-07-07.

## Цель

Устранить практический clean-install deadlock, при котором dynamic trainer игнорировал весь historical candle backfill и ожидал около 1206 новых часов после установки, сохранив temporal validation, point-in-time provenance, cost stress и fail-closed promotion.

## Исправления

- Добавлен режим `historical_frozen_dynamic_bootstrap`:
  - используется последний свежий committed dynamic universe snapshot;
  - snapshot проходит schema/policy/record SHA-256 validation;
  - execution-eligible cohort фиксируется до preflight и повторно сверяется перед fit и quality gate;
  - `AUTO_TRAIN_MAX_SYMBOLS` применяется только после текущего dynamic ranking и только к bootstrap cohort.
- Historical candles выбранного cohort теперь учитываются в пороге 1206 уникальных часов.
- Для часов до первой локально сохранённой instrument-spec записи разрешён строго ограниченный fallback на earliest locally observed tick:
  - только до первого `received_at`;
  - никогда не закрывает поздние gaps;
  - entry дополнительно ухудшается на `AUTO_TRAIN_BOOTSTRAP_INSTRUMENT_SPEC_EXTRA_TICKS`.
- Exact `prospective_dynamic_replay` не использует full-sample candle-coverage preselection, чтобы исключить survivorship/selection look-ahead.
- Trainer дешёво проверяет возможную длину prospective rollout до загрузки годового набора свечей.
- После накопления достаточного exact prospective evidence trainer автоматически запускает переобучение и заменяет bootstrap artifact.
- Scheduled retraining считает новые timestamps только внутри exact training symbol scope.
- Усилена проверка `training_data_profile`: timezone-aware timestamps, согласованность counts/ranges/coverage и проверка identity hashes.
- Bootstrap artifact получает явные `training_universe_mode` и immutable evidence; quality gate отклоняет mode/replay/spec/cohort contradictions.
- Bootstrap snapshot обязан быть свежим; stale/future snapshot не используется.

## Конфигурация

Добавлены безопасные defaults:

```env
AUTO_TRAIN_DYNAMIC_BOOTSTRAP_ENABLED=true
AUTO_TRAIN_BOOTSTRAP_MIN_SYMBOLS=3
AUTO_TRAIN_BOOTSTRAP_INSTRUMENT_SPEC_EXTRA_TICKS=1
```

## Совместимость

- Alembic migration не добавляется.
- API contract не изменяется.
- Existing active artifact продолжает работать.
- После обновления нужно перезапустить worker и trainer.
- Ни один holdout, calibration, policy, EV/RR, cost-stress, experiment-governance или risk threshold не снижен.

## Ограничения

Bootstrap не выдаётся за точный historical dynamic replay. До накопления prospective evidence остаются явно записанные ограничения: текущий frozen cohort вместо исторической membership, отсутствие архивных bid/ask/depth и использование conservative tick proxy до первой локальной instrument-spec записи.
