# Changelog

Все существенные изменения текущей линии фиксируются здесь начиная с версии 1.51.1. История до 1.51.1 отсутствовала во входном release-архиве и не реконструируется задним числом без доказательств.

## 1.52.1 — 2026-07-08

### Fixed

- Недостаток post-feature/post-label history для purged expanding walk-forward больше не считается аварийным падением background trainer.
- Walk-forward capacity теперь рассчитывается одним общим контрактом и сообщает actual/required timestamps, block size, initial train и purge requirements.
- Candidate build проверяет capacity до основного model fit, когда final holdout metadata доступна.
- Expected data shortage завершается как `SUCCESS` job с внутренним статусом `DEFERRED`, сохраняет incumbent и переводит trainer в healthy `WAITING`.
- Повторная bootstrap-попытка после deferral ждёт новых timestamps или material dataset change вместо tight error loop.
- JSON formatter больше не отбрасывает безопасные decision-time contract diagnostics; warning содержит reason code, lag, limit и sanitized contract mismatch values.

### Compatibility

- Миграций БД, новых переменных окружения и API-breaking changes нет.
- Walk-forward, purge, holdout, quality, policy и promotion thresholds не снижены.
- После обновления требуется перезапуск worker и trainer.

## 1.52.0 — 2026-07-07

### Fixed

- Устранено обязательное ожидание примерно 50 суток перед первой dynamic training attempt на чистой базе.
- Historical backfill теперь используется только внутри свежего hash-bound frozen execution cohort и не выдаётся за historical dynamic replay.
- Добавлен ограниченный conservative tick-size fallback для часов до первой локальной instrument-spec записи.
- Exact prospective replay больше не применяет full-sample candle-coverage symbol preselection.
- Training trigger/profile/evidence получили fail-closed identity, hash, timestamp и cohort validation.
- Scheduled retraining считает новые часы только внутри exact fitted symbol scope.
- Stale universe snapshot не может стать bootstrap cohort.

### Added

- Режимы `historical_frozen_dynamic_bootstrap` и `prospective_dynamic_replay` с автоматическим upgrade retraining.
- Три bootstrap configuration variables и regression tests cold-start path.
- Отдельный audit/iteration evidence по econometric и operational ограничениям.

### Compatibility

- Миграций БД и API-breaking changes нет.
- Existing active artifacts продолжают работать.
- После обновления требуется перезапуск worker и trainer.
- Quality, policy, experiment, cost-stress и risk thresholds не снижены.

## 1.51.1 — 2026-07-07

### Fixed

- Release verification больше не принимает самосогласованный, но неполный `SHA256SUMS` как достаточное доказательство готовности архива.
- Добавлена fail-closed проверка обязательных governance, security, operations и QA документов.
- Добавлена проверка совпадения версии в `pyproject.toml`, `app/__init__.py` и README.
- Добавлены обязательные version-specific patch notes и iteration report.

### Added

- Восстановлены `docs/QA_REPORT.md`, `docs/SPEC_COMPLIANCE.md`, `docs/TRACEABILITY.md` и базовый комплект эксплуатационной документации.
- Добавлены regression tests для неполного release tree и version drift.

### Compatibility

- Миграций БД, новых переменных окружения и изменений API нет.
- Торговая, ML и risk-математика не изменялась.
